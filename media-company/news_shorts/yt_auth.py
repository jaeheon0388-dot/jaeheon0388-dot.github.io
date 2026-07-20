#!/usr/bin/env python3
"""YouTube OAuth 최초 인증 스크립트 (1회 실행).

YT_CLIENT_SECRET_PATH의 OAuth 클라이언트로 브라우저 인증을 진행하고
YT_TOKEN_PATH에 토큰을 저장한다. 이후 pipeline.py가 자동으로 갱신해 사용.

VPS 등 브라우저 없는 환경이면: 로컬 PC에서 이 스크립트를 실행해 토큰 파일을
만든 뒤, 해당 파일만 VPS의 YT_TOKEN_PATH 경로로 복사하면 된다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

from common import envload  # noqa: E402

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main():
    client_secret = envload.get("YT_CLIENT_SECRET_PATH", required=True)
    token_path = Path(envload.get("YT_TOKEN_PATH", required=True))
    flow = InstalledAppFlow.from_client_secrets_file(client_secret, SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"토큰 저장 완료: {token_path}")


if __name__ == "__main__":
    main()
