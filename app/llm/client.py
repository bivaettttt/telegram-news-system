"""
LLM client — Chat Completions API (OpenAI / Groq / OpenRouter).

ИСПРАВЛЕНИЯ:
  - 429 Rate Limit: сразу бросает RateLimitError с retry_after секундами.
    НЕ ждёт inline — это блокировало весь pipeline на 256+ секунд.
    Вызывающий код (rewrite_news.py) сам решает что делать (останавливает батч).
  - Убран fallback на /responses endpoint — Groq его не поддерживает (→ 400).
  - Timeout: 2 retry с 5с паузой, затем LLMClientError.
  - Детальный парсинг retry_after из заголовков и JSON-тела Groq.
"""
from __future__ import annotations

import json
import re
import time

import httpx

from app.core.config import settings


class LLMClientError(RuntimeError):
    """Постоянная ошибка LLM — повтор не поможет."""
    pass


class RateLimitError(LLMClientError):
    """
    429 Too Many Requests.
    retry_after — сколько секунд ждать перед следующим запросом.
    """
    def __init__(self, retry_after: int = 60) -> None:
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded, retry after {retry_after}s")


def _extract_json_from_text(text: str) -> dict:
    """Парсит JSON из ответа LLM, убирая markdown-фенсы если есть."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def _parse_retry_after(resp: httpx.Response) -> int:
    """Извлекает время ожидания из 429-ответа Groq."""
    # 1. Стандартные HTTP заголовки
    for header in ("retry-after", "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
        raw = resp.headers.get(header)
        if raw:
            try:
                return max(5, int(float(raw)))
            except (ValueError, TypeError):
                pass

    # 2. JSON-тело Groq: {"error": {"message": "Please try again in 45.3s."}}
    try:
        body = resp.json()
        msg = str(body.get("error", {}).get("message", ""))
        m = re.search(r"try again in (\d+(?:\.\d+)?)\s*s", msg, re.IGNORECASE)
        if m:
            return max(5, int(float(m.group(1))) + 3)  # +3с запаса
    except Exception:
        pass

    return 60  # дефолт


class ResponsesClient:
    def __init__(self) -> None:
        self.base_url = settings.openai_base_url.rstrip("/")
        self.api_key = settings.openai_api_key
        self.model = settings.openai_model
        self.timeout = settings.llm_timeout_seconds

    @property
    def enabled(self) -> bool:
        return bool(settings.llm_rewrite_enabled and self.api_key)

    def create_json(self, system_prompt: str, user_prompt: str) -> dict:
        """
        Вызывает /chat/completions и возвращает распарсенный JSON.

        Raises:
            RateLimitError  — если Groq вернул 429. НЕ ждём здесь.
            LLMClientError  — при других ошибках (4xx, парсинг, timeout).
        """
        if not self.enabled:
            raise LLMClientError("LLM disabled or OPENAI_API_KEY not set")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        }

        MAX_TIMEOUT_RETRIES = 2

        with httpx.Client(timeout=self.timeout) as client:
            for attempt in range(MAX_TIMEOUT_RETRIES + 1):
                try:
                    resp = client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )

                    # 429 — пробрасываем немедленно, без ожидания
                    if resp.status_code == 429:
                        raise RateLimitError(_parse_retry_after(resp))

                    resp.raise_for_status()

                    data = resp.json()
                    text = data["choices"][0]["message"]["content"]
                    return _extract_json_from_text(text)

                except RateLimitError:
                    raise  # пробрасываем дальше без retry

                except httpx.TimeoutException:
                    if attempt < MAX_TIMEOUT_RETRIES:
                        time.sleep(5)
                        continue
                    raise LLMClientError(
                        f"LLM timeout after {MAX_TIMEOUT_RETRIES + 1} attempts"
                    )

                except (KeyError, json.JSONDecodeError, ValueError) as exc:
                    raise LLMClientError(f"LLM response parse error: {exc}") from exc

                except httpx.HTTPStatusError as exc:
                    raise LLMClientError(
                        f"LLM HTTP {exc.response.status_code}: {exc}"
                    ) from exc

        raise LLMClientError("LLM: unexpected exit from retry loop")