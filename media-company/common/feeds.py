"""RSS/Atom 피드 수집 (표준 라이브러리 파서만 사용)."""
import hashlib
import html
import re
import xml.etree.ElementTree as ET

import requests

USER_AGENT = "Mozilla/5.0 (compatible; media-company-pipeline/1.0)"
ATOM_NS = "{http://www.w3.org/2005/Atom}"


def _strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def fetch_rss(url, limit=20):
    """RSS 2.0 / Atom 피드에서 [{id, title, summary, link}] 목록을 반환."""
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    items = []
    for item in root.iter("item"):  # RSS 2.0
        title = _strip_html(item.findtext("title", ""))
        link = (item.findtext("link") or "").strip()
        summary = _strip_html(item.findtext("description", ""))
        items.append((title, link, summary))
    if not items:  # Atom
        for entry in root.iter(f"{ATOM_NS}entry"):
            title = _strip_html(entry.findtext(f"{ATOM_NS}title", ""))
            link_el = entry.find(f"{ATOM_NS}link")
            link = link_el.get("href", "") if link_el is not None else ""
            summary = _strip_html(entry.findtext(f"{ATOM_NS}summary", "")
                                  or entry.findtext(f"{ATOM_NS}content", ""))
            items.append((title, link, summary))

    results = []
    for title, link, summary in items[:limit]:
        if not title:
            continue
        uid = hashlib.sha1((link or title).encode("utf-8")).hexdigest()[:16]
        results.append({"id": uid, "title": title, "link": link,
                        "summary": summary[:500]})
    return results


def collect_candidates(urls, limit_per_feed=15):
    """여러 피드에서 후보를 모은다. 개별 피드 실패는 건너뛴다."""
    candidates = []
    for url in urls:
        try:
            candidates.extend(fetch_rss(url, limit=limit_per_feed))
        except Exception as e:  # noqa: BLE001
            print(f"[feeds] 피드 수집 실패({url}): {e}")
    return candidates
