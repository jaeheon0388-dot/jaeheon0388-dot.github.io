"""media-company 루트의 .env를 로드하고 환경변수를 읽는 헬퍼."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
_loaded = False


def ensure_env():
    global _loaded
    if not _loaded:
        load_dotenv(ROOT / ".env")
        _loaded = True


def get(name, default=None, required=False):
    ensure_env()
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(
            f"환경변수 {name}이(가) 비어 있습니다. media-company/.env를 확인하세요 "
            f"(.env.example 참고)."
        )
    return value
