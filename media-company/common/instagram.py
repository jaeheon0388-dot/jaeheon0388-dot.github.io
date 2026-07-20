"""Instagram Graph API 발행 헬퍼.

발행 라우팅은 호출하는 파이프라인이 자기 전용 .env 토큰을 넘겨서 결정한다 —
이 모듈은 어떤 계정으로 보낼지 스스로 판단하지 않는다.

주의: Graph API는 로컬 파일 업로드를 지원하지 않고 '공개적으로 접근 가능한
이미지 URL'만 받는다 (image_url 파라미터). PUBLIC_MEDIA_BASE_URL 필요.
https://developers.facebook.com/docs/instagram-platform/content-publishing
"""
import time

import requests

GRAPH = "https://graph.facebook.com/v21.0"


def _post(url, data):
    resp = requests.post(url, data=data, timeout=60)
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"Graph API 오류: {body['error']}")
    return body


def _wait_ready(container_id, token, timeout_sec=300):
    """미디어 컨테이너가 FINISHED 될 때까지 대기."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        resp = requests.get(f"{GRAPH}/{container_id}",
                            params={"fields": "status_code", "access_token": token},
                            timeout=30).json()
        status = resp.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"미디어 컨테이너 처리 실패: {resp}")
        time.sleep(5)
    raise TimeoutError("미디어 컨테이너 처리 대기 시간 초과")


def publish_single(account_id, token, image_url, caption):
    """단일 이미지 발행. 게시물 permalink 반환."""
    container = _post(f"{GRAPH}/{account_id}/media",
                      {"image_url": image_url, "caption": caption,
                       "access_token": token})
    _wait_ready(container["id"], token)
    return _publish(account_id, token, container["id"])


def publish_carousel(account_id, token, image_urls, caption):
    """캐러셀(2~10장) 발행. 게시물 permalink 반환."""
    if not 2 <= len(image_urls) <= 10:
        raise ValueError(f"캐러셀은 2~10장이어야 합니다 (현재 {len(image_urls)}장)")
    children = []
    for url in image_urls:
        c = _post(f"{GRAPH}/{account_id}/media",
                  {"image_url": url, "is_carousel_item": "true",
                   "access_token": token})
        _wait_ready(c["id"], token)
        children.append(c["id"])
    carousel = _post(f"{GRAPH}/{account_id}/media",
                     {"media_type": "CAROUSEL", "children": ",".join(children),
                      "caption": caption, "access_token": token})
    _wait_ready(carousel["id"], token)
    return _publish(account_id, token, carousel["id"])


def _publish(account_id, token, creation_id):
    result = _post(f"{GRAPH}/{account_id}/media_publish",
                   {"creation_id": creation_id, "access_token": token})
    media_id = result["id"]
    permalink = requests.get(f"{GRAPH}/{media_id}",
                             params={"fields": "permalink", "access_token": token},
                             timeout=30).json().get("permalink", f"media_id={media_id}")
    return permalink
