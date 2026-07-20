#!/usr/bin/env python3
"""뷰티 콘텐츠 파이프라인 → 인스타그램 뷰티 계정(IG_BEAUTY_* 전용).

humor 파이프라인과 동일 구조. 차이: 소재(뷰티 트렌드/팁),
산출물(단일 이미지 또는 캐러셀 — config.yaml의 format), IG_BEAUTY 계정 발행.

실행: python beauty/pipeline.py [--dry-run | --auto]
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import envload, feeds, image_utils, instagram, llm, usedlog  # noqa: E402
from common import telegram_notify as tg  # noqa: E402

PIPELINE_NAME = "beauty(뷰티)"
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
USED_LOG = OUTPUT_DIR / "used_log.json"


def load_config():
    with open(BASE_DIR / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def select_material(candidates, cfg):
    numbered = "\n".join(
        f"{i}. {c['title']} — {c['summary'][:150]}" for i, c in enumerate(candidates))
    prompt = (
        "다음은 뷰티 콘텐츠 소재 후보 목록이다. 인스타그램 뷰티 계정 팔로워"
        "(2030 여성 중심)에게 실질적으로 유용하거나 트렌디한 소재 1건을 골라라.\n"
        "특정 제품 광고성 기사, 근거 없는 효능 주장은 제외한다.\n\n"
        f"{numbered}\n\n"
        'JSON으로만 답하라: {"choice": <번호>, "reason": "<선정 이유>"}')
    result = llm.generate_json("classify", prompt, temperature=0.3)
    idx = int(result["choice"])
    if not 0 <= idx < len(candidates):
        raise ValueError(f"LLM이 잘못된 번호를 골랐습니다: {idx}")
    print(f"[select] {candidates[idx]['title']} (이유: {result.get('reason', '')})")
    return candidates[idx]


def write_content(item, cfg):
    """format=single이면 카드 1장, carousel이면 4~6장 + 캡션 생성."""
    tone = cfg.get("tone", "친근하고 신뢰감 있는 존댓말 톤")
    fmt = cfg.get("format", "carousel")
    count_rule = ("카드 1장" if fmt == "single" else "카드 4~6장")
    prompt = (
        f"소재: {item['title']}\n내용 요약: {item['summary']}\n\n"
        f"위 소재로 인스타그램 뷰티 콘텐츠({count_rule})를 만들어라. 톤: {tone}\n"
        "규칙:\n"
        "- 원문을 그대로 옮기지 말 것. 자체 해석/실전 팁을 반드시 덧붙일 것.\n"
        "- 각 카드는 title(짧은 헤드라인)과 body(2~4문장).\n"
        "- caption은 게시물 본문용 2~3문장 (저장/공유 유도 포함).\n\n"
        "JSON으로만 답하라: "
        '{"cards": [{"title": "...", "body": "..."}], "caption": "..."}')
    result = llm.generate_json("writing", prompt, max_tokens=3000)
    cards = result["cards"]
    if fmt == "single":
        cards = cards[:1]
    elif not 2 <= len(cards) <= 10:
        raise ValueError(f"카드 수가 비정상입니다: {len(cards)}장")
    return cards, result.get("caption", item["title"])


def render_cards(cards, cfg, out_dir):
    template = BASE_DIR / "templates" / cfg.get("template", "card_bg.png")
    footer = cfg.get("footer_text", "")
    paths = []
    for i, card in enumerate(cards, start=1):
        path = out_dir / f"card_{i}.png"
        image_utils.render_card(
            path, title=card.get("title"), body=card.get("body"),
            template_path=template if template.exists() else None,
            bg_color=(250, 244, 240), title_color=(120, 72, 80),
            body_color=(60, 55, 58), footer=footer or None,
            footer_color=(160, 140, 145))
        paths.append(path)
    return paths


def build_caption(caption, cfg):
    hashtags = " ".join(cfg.get("hashtags", []))
    return f"{caption}\n\n{hashtags}".strip()


def publish(image_paths, caption):
    """IG_BEAUTY 계정에 발행. 이 파이프라인은 IG_BEAUTY_* 토큰만 사용한다."""
    token = envload.get("IG_BEAUTY_ACCESS_TOKEN", required=True)
    account_id = envload.get("IG_BEAUTY_ACCOUNT_ID", required=True)
    base_url = envload.get("PUBLIC_MEDIA_BASE_URL", required=True).rstrip("/")
    root = BASE_DIR.parent
    urls = [f"{base_url}/{p.resolve().relative_to(root).as_posix()}" for p in image_paths]
    if len(urls) == 1:
        return instagram.publish_single(account_id, token, urls[0], caption)
    return instagram.publish_carousel(account_id, token, urls, caption)


def main():
    parser = argparse.ArgumentParser(description=PIPELINE_NAME)
    parser.add_argument("--dry-run", action="store_true",
                        help="발행 없이 생성물만 output/에 저장")
    parser.add_argument("--auto", action="store_true",
                        help="승인 단계 생략 후 즉시 발행 (검증 완료 후 사용)")
    args = parser.parse_args()
    cfg = load_config()

    sources = cfg.get("sources") or []
    if not sources:
        raise SystemExit("config.yaml의 sources가 비어 있습니다. RSS URL을 기입하세요.")
    candidates = feeds.collect_candidates(sources)
    used = usedlog.load_used_ids(USED_LOG)
    candidates = [c for c in candidates if c["id"] not in used]
    if not candidates:
        tg.notify(f"ℹ️ {PIPELINE_NAME}: 새 소재가 없어 이번 회차를 건너뜁니다.")
        return
    print(f"[collect] 후보 {len(candidates)}건")

    item = select_material(candidates, cfg)
    cards, caption = write_content(item, cfg)
    caption = build_caption(caption, cfg)

    out_dir = OUTPUT_DIR / date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    image_paths = render_cards(cards, cfg, out_dir)
    (out_dir / "post.json").write_text(
        json.dumps({"source": item, "cards": cards, "caption": caption},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[render] 카드 {len(image_paths)}장 → {out_dir}")

    if args.dry_run:
        print("[dry-run] 발행 생략. 생성물만 저장했습니다.")
        return
    usedlog.record_used(USED_LOG, item)

    if not args.auto:
        preview = "\n\n".join(f"[{c['title']}]\n{c['body']}" for c in cards)
        approved = tg.request_approval(PIPELINE_NAME, "인스타그램 뷰티 계정",
                                       f"{preview}\n\n캡션: {caption}",
                                       media_paths=image_paths)
        if not approved:
            print("[approval] 거절/시간초과 — 발행 중단")
            return

    try:
        permalink = publish(image_paths, caption)
        tg.notify(f"✅ {PIPELINE_NAME} 발행 성공\n{permalink}")
        print(f"[publish] 성공: {permalink}")
    except Exception as e:  # noqa: BLE001
        tg.notify(f"❌ {PIPELINE_NAME} 발행 실패: {e}")
        raise


if __name__ == "__main__":
    main()
