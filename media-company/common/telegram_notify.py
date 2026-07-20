"""텔레그램 승인 요청/알림 발송."""
import time
import uuid
from pathlib import Path

import requests

from common import envload

APPROVAL_TIMEOUT_MIN = 60  # 승인 대기 최대 시간(분)
POLL_INTERVAL_SEC = 5


def _api(method):
    token = envload.get("TELEGRAM_BOT_TOKEN", required=True)
    return f"https://api.telegram.org/bot{token}/{method}"


def _chat_id():
    return envload.get("TELEGRAM_CHAT_ID", required=True)


def notify(message):
    """단순 알림 (성공/실패 보고용). 텔레그램 미설정 시 콘솔에만 출력."""
    try:
        requests.post(_api("sendMessage"),
                      json={"chat_id": _chat_id(), "text": message},
                      timeout=30).raise_for_status()
    except Exception as e:  # noqa: BLE001 - 알림 실패가 파이프라인을 죽이면 안 됨
        print(f"[telegram] 알림 실패({e}): {message}")


def send_media(media_path, caption=None):
    """사진(.png/.jpg) 또는 영상(.mp4) 파일 전송."""
    path = Path(media_path)
    is_video = path.suffix.lower() in (".mp4", ".mov", ".webm")
    method, field = ("sendVideo", "video") if is_video else ("sendPhoto", "photo")
    with open(path, "rb") as f:
        resp = requests.post(
            _api(method),
            data={"chat_id": _chat_id(), "caption": caption or ""},
            files={field: f},
            timeout=300,
        )
    resp.raise_for_status()


def request_approval(pipeline_name, target_account, preview_text, media_paths=None):
    """미리보기를 보내고 [승인/거절] 버튼 응답을 대기한다. 승인 시 True.

    media_paths: 미리보기로 함께 보낼 이미지/영상 경로 목록 (최대 5개 전송).
    """
    nonce = uuid.uuid4().hex[:10]
    for p in (media_paths or [])[:5]:
        try:
            send_media(p)
        except Exception as e:  # noqa: BLE001
            print(f"[telegram] 미디어 전송 실패({p}): {e}")

    text = (f"🟡 발행 승인 요청\n"
            f"파이프라인: {pipeline_name}\n"
            f"발행 대상: {target_account}\n"
            f"----------------\n{preview_text[:3500]}")
    keyboard = {"inline_keyboard": [[
        {"text": "✅ 승인", "callback_data": f"approve:{nonce}"},
        {"text": "❌ 거절", "callback_data": f"reject:{nonce}"},
    ]]}
    resp = requests.post(_api("sendMessage"),
                         json={"chat_id": _chat_id(), "text": text,
                               "reply_markup": keyboard},
                         timeout=30)
    resp.raise_for_status()

    print(f"[telegram] 승인 대기 중... (최대 {APPROVAL_TIMEOUT_MIN}분)")
    return _wait_for_callback(nonce)


def _wait_for_callback(nonce):
    deadline = time.time() + APPROVAL_TIMEOUT_MIN * 60
    offset = None
    while time.time() < deadline:
        params = {"timeout": 30, "allowed_updates": '["callback_query"]'}
        if offset is not None:
            params["offset"] = offset
        try:
            resp = requests.get(_api("getUpdates"), params=params, timeout=60)
            updates = resp.json().get("result", [])
        except Exception as e:  # noqa: BLE001
            print(f"[telegram] getUpdates 실패, 재시도: {e}")
            time.sleep(POLL_INTERVAL_SEC)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            cq = upd.get("callback_query")
            if not cq:
                continue
            data = cq.get("data", "")
            if not data.endswith(f":{nonce}"):
                continue
            approved = data.startswith("approve:")
            try:
                requests.post(_api("answerCallbackQuery"),
                              json={"callback_query_id": cq["id"],
                                    "text": "승인됨" if approved else "거절됨"},
                              timeout=30)
            except Exception:  # noqa: BLE001
                pass
            notify("✅ 승인됨 — 발행을 진행합니다." if approved
                   else "❌ 거절됨 — 발행을 중단합니다.")
            return approved
        time.sleep(POLL_INTERVAL_SEC)
    notify(f"⏰ 승인 대기 시간({APPROVAL_TIMEOUT_MIN}분) 초과 — 발행을 중단합니다.")
    return False
