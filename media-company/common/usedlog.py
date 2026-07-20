"""사용한 소재 기록 (파이프라인별 output/used_log.json — 파이프라인 간 공유 금지)."""
import json
from datetime import datetime
from pathlib import Path


def load_used_ids(log_path):
    path = Path(log_path)
    if not path.exists():
        return set()
    entries = json.loads(path.read_text(encoding="utf-8"))
    return {e["id"] for e in entries}


def record_used(log_path, item):
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    entries.append({"id": item["id"], "title": item.get("title", ""),
                    "link": item.get("link", ""),
                    "used_at": datetime.now().isoformat(timespec="seconds")})
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2),
                    encoding="utf-8")
