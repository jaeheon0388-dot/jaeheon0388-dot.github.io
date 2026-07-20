"""OpenRouter 호출 래퍼. LLM은 콘텐츠 생성만 담당한다 — 발행 라우팅 금지."""
import json
import time

import requests

from common import envload

API_URL = "https://openrouter.ai/api/v1/chat/completions"

# task_type → .env 모델 변수 매핑
MODEL_ENV = {
    "writing": "MODEL_WRITING",
    "analysis": "MODEL_ANALYSIS",
    "classify": "MODEL_CLASSIFY",
}


def generate(task_type, prompt, system=None, temperature=0.7, max_tokens=2000):
    """task_type(writing|analysis|classify)에 따라 모델을 라우팅해 텍스트를 생성한다.

    실패 시 1회 재시도, 그래도 실패하면 텔레그램 에러 알림 후 예외를 던진다.
    """
    if task_type not in MODEL_ENV:
        raise ValueError(f"알 수 없는 task_type: {task_type}")
    api_key = envload.get("OPENROUTER_API_KEY", required=True)
    model = envload.get(MODEL_ENV[task_type], required=True)

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    last_error = None
    for attempt in range(2):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001 - 재시도 후 보고
            last_error = e
            if attempt == 0:
                time.sleep(3)

    from common import telegram_notify

    telegram_notify.notify(f"⚠️ LLM 호출 실패 (task={task_type}, model={model}): {last_error}")
    raise RuntimeError(f"LLM 호출 2회 실패: {last_error}") from last_error


def generate_json(task_type, prompt, system=None, temperature=0.7, max_tokens=2000):
    """generate() 후 응답에서 JSON 객체를 추출해 파싱한다."""
    text = generate(task_type, prompt, system=system, temperature=temperature,
                    max_tokens=max_tokens)
    return parse_json_block(text)


def parse_json_block(text):
    """LLM 응답에서 첫 JSON 객체/배열을 찾아 파싱한다 (```json 펜스 허용)."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    if start == -1:
        raise ValueError(f"LLM 응답에 JSON이 없습니다: {text[:200]}")
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(text[start:])
    return obj
