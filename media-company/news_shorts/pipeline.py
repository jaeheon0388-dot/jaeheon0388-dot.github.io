#!/usr/bin/env python3
"""뉴스 숏폼 파이프라인 → 유튜브 (YT_* 전용).

단계: 뉴스 수집 → 기사 선별(LLM) → 대본 생성(LLM) → edge-tts 음성 →
ffmpeg 세로(1080x1920) 렌더링 → 텔레그램 승인 → YouTube 업로드.

실행: python news_shorts/pipeline.py [--dry-run | --auto]
"""
import argparse
import asyncio
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import envload, feeds, image_utils, llm, usedlog  # noqa: E402
from common import telegram_notify as tg  # noqa: E402

PIPELINE_NAME = "news_shorts(뉴스 숏폼)"
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
USED_LOG = OUTPUT_DIR / "used_log.json"
W, H = 1080, 1920


def load_config():
    with open(BASE_DIR / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def select_article(candidates, cfg):
    numbered = "\n".join(
        f"{i}. {c['title']} — {c['summary'][:150]}" for i, c in enumerate(candidates))
    prompt = (
        f"다음은 뉴스 기사 후보 목록이다({cfg.get('news_topic', '일반')} 분야). "
        "50초 내외 유튜브 숏폼으로 만들었을 때 시청 유지율이 높을 기사 1건을 골라라.\n"
        "단순 보도자료·광고성 기사·자극적 루머는 제외한다.\n\n"
        f"{numbered}\n\n"
        'JSON으로만 답하라: {"choice": <번호>, "reason": "<선정 이유>"}')
    result = llm.generate_json("classify", prompt, temperature=0.3)
    idx = int(result["choice"])
    if not 0 <= idx < len(candidates):
        raise ValueError(f"LLM이 잘못된 번호를 골랐습니다: {idx}")
    print(f"[select] {candidates[idx]['title']} (이유: {result.get('reason', '')})")
    return candidates[idx]


def write_script(item, cfg):
    """45~55초 분량 대본. 기사 요약이 아닌 자체 관점 코멘트 포함."""
    tone = cfg.get("tone", "빠르고 명확한 존댓말")
    prompt = (
        f"기사 제목: {item['title']}\n기사 요약: {item['summary']}\n\n"
        "위 기사로 유튜브 숏폼(세로 영상) 내레이션 대본을 써라.\n"
        "규칙:\n"
        f"- 낭독 시 45~55초 분량 (한국어 280~380자). 톤: {tone}\n"
        "- 단순 기사 요약 금지. 후반부에 반드시 자체 관점 코멘트/시사점을 넣을 것.\n"
        "- 첫 문장은 3초 안에 관심을 끄는 훅.\n"
        "- 영상 제목(title)은 40자 이내, 설명(description)은 2~3문장.\n\n"
        "JSON으로만 답하라: "
        '{"title": "...", "script": "...", "description": "..."}')
    result = llm.generate_json("writing", prompt, max_tokens=2000)
    for key in ("title", "script", "description"):
        if not result.get(key):
            raise ValueError(f"대본 응답에 {key}가 없습니다")
    return result


async def _tts(script, voice, mp3_path, srt_path):
    import edge_tts

    communicate = edge_tts.Communicate(script, voice)
    submaker = edge_tts.SubMaker()
    with open(mp3_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                submaker.feed(chunk)
    srt_path.write_text(submaker.get_srt(), encoding="utf-8")


def synthesize_voice(script, cfg, out_dir):
    """edge-tts로 음성(mp3) + 자막(srt) 생성."""
    voice = cfg.get("tts_voice", "ko-KR-SunHiNeural")
    mp3_path = out_dir / "voice.mp3"
    srt_path = out_dir / "subs.srt"
    asyncio.run(_tts(script, voice, mp3_path, srt_path))
    return mp3_path, srt_path


def render_video(title, mp3_path, srt_path, cfg, out_dir):
    """배경 이미지 + 자막 + 음성 합성 → 1080x1920 mp4."""
    bg_path = out_dir / "bg.png"
    image_utils.render_card(bg_path, title=title, size=(W, H),
                            bg_color=(12, 14, 24),
                            footer=cfg.get("channel_name", ""))
    video_path = out_dir / "short.mp4"
    font_name = cfg.get("subtitle_font_name", "NanumGothic")
    style = (f"FontName={font_name},FontSize=16,PrimaryColour=&H00FFFFFF,"
             "OutlineColour=&H00000000,Outline=2,BorderStyle=1,"
             "Alignment=2,MarginV=90")
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", bg_path.name, "-i", mp3_path.name,
        "-vf", f"subtitles={srt_path.name}:force_style='{style}'",
        "-c:v", "libx264", "-preset", "fast", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "128k", "-pix_fmt", "yuv420p",
        "-shortest", video_path.name,
    ]
    # 자막 필터의 경로 이스케이프 문제를 피하려고 out_dir에서 상대경로로 실행
    result = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 렌더링 실패:\n{result.stderr[-2000:]}")
    return video_path


def upload_youtube(video_path, meta, cfg):
    """YouTube Data API 업로드. 심사 전 앱은 영상이 비공개(private) 고정됨."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    token_path = envload.get("YT_TOKEN_PATH", required=True)
    if not Path(token_path).exists():
        raise RuntimeError(
            f"YouTube 토큰({token_path})이 없습니다. 먼저 인증을 실행하세요:\n"
            "  python news_shorts/yt_auth.py")
    creds = Credentials.from_authorized_user_file(
        token_path, ["https://www.googleapis.com/auth/youtube.upload"])
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        Path(token_path).write_text(creds.to_json(), encoding="utf-8")

    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": meta["title"][:100],
            "description": meta["description"],
            "tags": cfg.get("yt_tags", []),
            "categoryId": "25",  # News & Politics
        },
        "status": {"privacyStatus": cfg.get("privacy", "private"),
                   "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(str(video_path), mimetype="video/mp4",
                            resumable=True, chunksize=4 * 1024 * 1024)
    request = youtube.videos().insert(part="snippet,status", body=body,
                                      media_body=media)
    response = None
    while response is None:
        _, response = request.next_chunk()
    return f"https://youtu.be/{response['id']}"


def main():
    parser = argparse.ArgumentParser(description=PIPELINE_NAME)
    parser.add_argument("--dry-run", action="store_true",
                        help="발행 없이 생성물만 output/에 저장")
    parser.add_argument("--auto", action="store_true",
                        help="승인 단계 생략 후 즉시 업로드 (검증 완료 후 사용)")
    args = parser.parse_args()
    cfg = load_config()

    # 1. 뉴스 수집
    sources = cfg.get("sources") or []
    if not sources:
        raise SystemExit("config.yaml의 sources가 비어 있습니다. 뉴스 RSS URL을 기입하세요.")
    candidates = feeds.collect_candidates(sources)
    used = usedlog.load_used_ids(USED_LOG)
    candidates = [c for c in candidates if c["id"] not in used]
    if not candidates:
        tg.notify(f"ℹ️ {PIPELINE_NAME}: 새 기사가 없어 이번 회차를 건너뜁니다.")
        return
    print(f"[collect] 후보 {len(candidates)}건")

    # 2~3. 기사 선별 + 대본 생성
    item = select_article(candidates, cfg)
    meta = write_script(item, cfg)

    out_dir = OUTPUT_DIR / date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "post.json").write_text(
        json.dumps({"source": item, **meta}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    # 4~5. TTS + 렌더링
    mp3_path, srt_path = synthesize_voice(meta["script"], cfg, out_dir)
    print(f"[tts] 음성/자막 생성 완료 → {mp3_path}")
    video_path = render_video(meta["title"], mp3_path, srt_path, cfg, out_dir)
    print(f"[render] 영상 렌더링 완료 → {video_path}")

    if args.dry_run:
        print("[dry-run] 업로드 생략. 생성물만 저장했습니다.")
        return
    usedlog.record_used(USED_LOG, item)

    # 6. 승인 요청 (영상 파일 발송)
    if not args.auto:
        approved = tg.request_approval(
            PIPELINE_NAME, "유튜브 채널",
            f"제목: {meta['title']}\n\n대본:\n{meta['script']}",
            media_paths=[video_path])
        if not approved:
            print("[approval] 거절/시간초과 — 업로드 중단")
            return

    # 7. 발행
    try:
        url = upload_youtube(video_path, meta, cfg)
        tg.notify(f"✅ {PIPELINE_NAME} 업로드 성공\n{url}\n"
                  "⚠️ API 앱 심사 전에는 비공개 상태로 업로드됩니다. "
                  "YouTube Studio에서 수동 공개가 필요합니다.")
        print(f"[publish] 성공: {url}")
    except Exception as e:  # noqa: BLE001
        tg.notify(f"❌ {PIPELINE_NAME} 업로드 실패: {e}")
        raise


if __name__ == "__main__":
    main()
