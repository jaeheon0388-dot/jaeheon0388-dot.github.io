# HANDOFF — AI 미디어 콘텐츠 파이프라인 이식 문서

## 1. 시스템 개요

콘텐츠 자동 발행 파이프라인 3개. **LLM은 콘텐츠 생성만 담당하고, 발행 라우팅(어느 계정/플랫폼)은 코드가 고정한다.** 각 파이프라인은 자기 전용 환경변수 토큰만 사용하며, 파이프라인 간 파일 공유는 없다(각자 자기 `output/`에만 읽고 씀). 발행 직전 텔레그램 승인 단계가 기본값이다.

| 파이프라인 | 콘텐츠 | 발행처 | 전용 토큰 |
|---|---|---|---|
| `humor/` | 유머 카드뉴스 (캐러셀) | 인스타 유머 계정 | `IG_HUMOR_*` |
| `beauty/` | 뷰티 팁 (단일/캐러셀) | 인스타 뷰티 계정 | `IG_BEAUTY_*` |
| `news_shorts/` | 뉴스 숏폼 (1080x1920) | 유튜브 | `YT_*` |

### 폴더 구조

```
media-company/
├── .env                  # 모든 토큰/키 (커밋 금지, .gitignore 처리됨)
├── .env.example          # .env 템플릿
├── requirements.txt
├── common/
│   ├── llm.py            # OpenRouter 래퍼 (task_type→모델 라우팅, 1회 재시도)
│   ├── telegram_notify.py# 승인 요청(인라인 버튼)/알림
│   ├── image_utils.py    # Pillow 카드 렌더링
│   ├── feeds.py          # RSS/Atom 수집 (표준 라이브러리 파서, 의존성 없음)
│   ├── usedlog.py        # 소재 중복 방지 기록
│   ├── instagram.py      # Graph API 발행 (토큰은 파이프라인이 주입)
│   └── envload.py        # .env 로더
├── humor/    pipeline.py, config.yaml, templates/, output/
├── beauty/   pipeline.py, config.yaml, output/
└── news_shorts/ pipeline.py, config.yaml, yt_auth.py, output/
```

각 파이프라인 흐름: RSS 수집 → LLM(classify) 소재 1건 선별(중복은 `output/used_log.json`으로 차단) → LLM(writing) 자체 재해석 문구/대본 생성(원문 복붙 금지) → 이미지/영상 렌더링 → `output/날짜/` 저장 → 텔레그램 승인 → 발행 → 결과 보고.

## 2. 사전 준비

### 시스템 의존성 (Ubuntu 기준)

```bash
sudo apt install -y ffmpeg fonts-nanum python3-pip
pip3 install -r requirements.txt
```

- **ffmpeg**: news_shorts 영상 렌더링 필수.
- **한글 폰트**: 카드 이미지와 영상 자막에 필요. `fonts-nanum` 설치 후 `.env`의 `FONT_PATH`에 `/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf` 지정. Windows는 `C:/Windows/Fonts/malgunbd.ttf`.
- Python 3.10+ 권장 (3.11에서 검증).

### 토큰 발급

| 항목 | 발급 위치 | 절차 요약 |
|---|---|---|
| OpenRouter | https://openrouter.ai/keys | 가입 → Create Key → `OPENROUTER_API_KEY` |
| Telegram | @BotFather | `/newbot` → 토큰 발급. 봇에게 아무 메시지 1개 보낸 뒤 `https://api.telegram.org/bot<토큰>/getUpdates`에서 `chat.id` 확인 → `TELEGRAM_CHAT_ID` |
| Instagram | https://business.facebook.com + https://developers.facebook.com | ① 인스타 계정을 **프로페셔널 계정**으로 전환하고 페이스북 페이지에 연결 ② Meta 개발자 앱 생성 ③ `instagram_basic`, `instagram_content_publish`, `pages_read_engagement` 권한의 **장기(60일) 토큰** 발급 ④ `GET /me/accounts` → 페이지의 `instagram_business_account.id`가 계정 ID. **계정별로 따로** 발급해 `IG_HUMOR_*` / `IG_BEAUTY_*`에 입력 |
| YouTube | https://console.cloud.google.com | 프로젝트 생성 → YouTube Data API v3 활성화 → OAuth 클라이언트(데스크톱 앱) JSON 다운로드 → `YT_CLIENT_SECRET_PATH`에 경로 지정 → `python news_shorts/yt_auth.py` 1회 실행(브라우저 인증)하면 `YT_TOKEN_PATH`에 토큰 저장. VPS(헤드리스)면 로컬 PC에서 인증 후 토큰 파일만 복사 |

### ⚠️ Instagram 발행의 공개 URL 제약

Graph API는 로컬 파일 업로드를 지원하지 않고 **공개적으로 접근 가능한 `image_url`**만 받는다. `.env`의 `PUBLIC_MEDIA_BASE_URL`에 `media-company/` 루트를 서빙하는 공개 베이스 URL을 넣어야 한다. 발행 시 URL은 `PUBLIC_MEDIA_BASE_URL/humor/output/2026-07-20/card_1.png` 형태로 조립된다. 방법 예시:

- GitHub Pages 저장소에 output을 push 후 해당 raw URL 사용
- VPS라면 nginx로 `media-company/`를 정적 서빙
- S3/R2 버킷에 output 동기화

## 3. .env 작성법

```bash
cp .env.example .env   # 후 각 값 채우기
```

`.env.example`의 주석에 각 항목 설명이 있다. 모델명 예시: `MODEL_WRITING=anthropic/claude-sonnet-4.5`, `MODEL_CLASSIFY=google/gemini-2.5-flash` (OpenRouter 모델 페이지에서 선택). `.env`는 `.gitignore`에 포함되어 커밋되지 않는다.

## 4. 실행/테스트 방법 (파이프라인 공통)

```bash
cd media-company

# 1단계: 발행 없이 생성물만 확인 (LLM 키 + FONT_PATH만 있으면 됨)
python3 humor/pipeline.py --dry-run     # → humor/output/날짜/ 확인

# 2단계: 승인 플로우 포함 실발행 (기본 모드)
python3 humor/pipeline.py               # 텔레그램으로 미리보기+[승인/거절] 버튼 도착

# 3단계: 검증 완료 후 자동 모드 (승인 생략)
python3 humor/pipeline.py --auto
```

beauty, news_shorts도 동일 (`python3 beauty/pipeline.py`, `python3 news_shorts/pipeline.py`). 시작 전 각 `config.yaml`의 `sources`를 **원하는 RSS로 교체**할 것 — 현재 값은 동작 확인용 기본값(Google News 검색 RSS)이다. `footer_text`/`channel_name`의 계정명도 실제 계정으로 바꿀 것.

- 승인 대기는 최대 60분(`common/telegram_notify.py`의 `APPROVAL_TIMEOUT_MIN`), 시간 초과 시 발행하지 않음.
- 소재 중복 방지 기록은 dry-run에서는 남기지 않는다(테스트 반복 가능). 실발행 모드에서는 승인 전에 기록되므로, 거절한 소재도 재사용되지 않는다.
- news_shorts는 **API 앱 심사(audit) 전에는 업로드 영상이 강제 비공개** 처리된다. 파이프라인이 업로드 후 "비공개 상태로 업로드됨, 수동 공개 필요"를 텔레그램으로 알린다.

## 5. 크론 등록

```bash
crontab -e
```

```cron
# 파이프라인별 개별 등록, 서로 다른 시각 (경로는 실제 설치 위치로)
0 9  * * * cd /home/user/media-company && python3 humor/pipeline.py >> humor/output/cron.log 2>&1
0 11 * * * cd /home/user/media-company && python3 beauty/pipeline.py >> beauty/output/cron.log 2>&1
0 18 * * * cd /home/user/media-company && python3 news_shorts/pipeline.py >> news_shorts/output/cron.log 2>&1
```

기본(승인) 모드로 걸어두면 매일 정해진 시각에 생성→텔레그램 승인 요청이 오고, 버튼만 누르면 발행된다. 몇 주 검증 후 `--auto`를 붙여 완전 자동으로 전환.

## 6. 헤르메스 연동

**헤르메스는 트리거만 담당한다.** 콘텐츠 생성·발행 로직은 전부 각 `pipeline.py` 안에 있고, 헤르메스는 "해당 스크립트를 실행"하는 역할만 한다. 어떤 계정에 발행할지는 스크립트가 자기 전용 토큰으로 고정하므로 헤르메스(또는 LLM)가 라우팅에 개입할 여지가 없다.

텔레그램 명령 → 파이프라인 실행 스킬 등록 예시:

```yaml
# 헤르메스 스킬 정의 예시
- name: run_humor_pipeline
  trigger: "유머 발행"           # 텔레그램에서 이 명령을 받으면
  action: shell
  command: cd /home/user/media-company && python3 humor/pipeline.py
- name: run_beauty_pipeline
  trigger: "뷰티 발행"
  action: shell
  command: cd /home/user/media-company && python3 beauty/pipeline.py
- name: run_news_pipeline
  trigger: "뉴스 발행"
  action: shell
  command: cd /home/user/media-company && python3 news_shorts/pipeline.py
```

실행 후의 승인/보고는 파이프라인이 자체적으로 텔레그램에 보내므로 헤르메스는 결과를 기다릴 필요 없다.

## 7. 자주 나는 에러와 해결법 (구현 중 실제로 만난 것)

| 증상 | 원인 | 해결 |
|---|---|---|
| `pip install feedparser` 중 `Failed building wheel for sgmllib3k` | feedparser의 오래된 빌드 의존성 | feedparser를 쓰지 않는다. 본 시스템은 표준 라이브러리 파서(`common/feeds.py`)로 구현되어 있어 해당 패키지가 필요 없음 |
| `ModuleNotFoundError: No module named '_cffi_backend'` 또는 `pyo3_runtime.PanicException` (google 라이브러리 import 시) | 시스템(apt) 설치 `cryptography`와 pip 환경 불일치 | `pip3 install --upgrade cffi cryptography` (그래도 안 되면 `--ignore-installed` 추가) |
| edge-tts에서 `SSL: CERTIFICATE_VERIFY_FAILED` 또는 연결 실패 | 방화벽/프록시가 `speech.platform.bing.com` 차단 또는 TLS 가로채기 | 해당 호스트로의 아웃바운드 443 허용 필요. 사내망이면 프록시 CA를 `SSL_CERT_FILE`로 지정. 폐쇄망에서는 edge-tts 사용 불가 |
| ffmpeg `subtitles` 필터가 자막 파일을 못 찾음 (경로에 한글/특수문자) | 필터 인자의 경로 이스케이프 문제 | 파이프라인은 `output/날짜/` 디렉토리에서 **상대경로**로 ffmpeg를 실행하도록 이미 처리되어 있음. 직접 실행할 때도 자막 파일이 있는 디렉토리에서 실행할 것 |
| 카드 이미지 한글이 □□□로 깨짐 / `FileNotFoundError: 한글 폰트가 없습니다` | `FONT_PATH` 미설정 또는 폰트 미설치 | `sudo apt install fonts-nanum` 후 `.env`의 `FONT_PATH` 지정 |
| Instagram 발행 시 `Graph API 오류` (media URL 관련) | `image_url`이 공개 접근 불가 | `PUBLIC_MEDIA_BASE_URL` 확인 — 브라우저 시크릿 창에서 이미지 URL이 열려야 함 |
| 텔레그램 승인 버튼을 눌러도 반응 없음 (`getUpdates` 409 Conflict) | 봇에 webhook이 설정돼 있으면 getUpdates 폴링과 충돌 | `https://api.telegram.org/bot<토큰>/deleteWebhook` 1회 호출 |
| YouTube 업로드는 성공했는데 영상이 비공개 | OAuth 앱이 아직 Google 심사 전 | 정상 동작. YouTube Studio에서 수동 공개하거나, 심사(App verification + API audit) 통과 후 자동 공개 가능 |
| `RuntimeError: 환경변수 ...이(가) 비어 있습니다` | `.env` 미작성 | `cp .env.example .env` 후 해당 값 입력 |

## 8. 검증 이력 (이식 시점 기준)

- 3개 파이프라인 모두 `--dry-run` 통합 테스트 통과 (LLM 응답은 목킹, RSS는 로컬 피드로 검증).
- 카드 이미지(1080x1080) 한글 렌더링, 숏폼 영상(1080x1920, 자막 번인) 렌더링 확인.
- **미검증(토큰 필요)**: OpenRouter 실호출, 텔레그램 실제 승인 플로우, Instagram/YouTube 실발행. 토큰 입력 후 반드시 4장의 1→2→3단계 순서로 검증할 것.
