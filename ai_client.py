from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

try:
    from openai import OpenAI, APIConnectionError, APIStatusError, APITimeoutError
except ImportError:
    OpenAI = None

from config import TOOLS_PROMPT

COMMAND_RE = re.compile(r"\[\[\s*(window|emote)\s*:\s*([a-z_]+)\s*(?::\s*([-\d\s,]+))?\s*\]\]", re.I)
OPEN_RE = re.compile(r"\[\[\s*open\s*:\s*([^\[\]]{1,80}?)\s*\]\]", re.I)
THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)


@dataclass
class Command:
    kind: str
    action: str
    args: list[int] = field(default_factory=list)
    value: str = ""


@dataclass
class AIReply:
    text: str
    commands: list[Command]


def parse_reply(raw: str) -> AIReply:
    raw = THINK_RE.sub("", raw or "")
    commands = [Command("open", "open", value=name.strip()) for name in OPEN_RE.findall(raw)]
    for kind, action, args in COMMAND_RE.findall(raw):
        nums = [int(n) for n in re.findall(r"-?\d+", args or "")]
        commands.append(Command(kind.lower(), action.lower(), nums))
    text = OPEN_RE.sub("", COMMAND_RE.sub("", raw))
    text = re.sub(r"[ \t]+\n", "\n", text).strip()
    return AIReply(text=text, commands=commands)


class AIError(Exception):
    pass


class AIClient:
    def __init__(self, api_key: str, base_url: str, model: str, system_prompt: str,
                 temperature: float = 0.7, history_length: int = 12):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.history_length = history_length
        self.history: list[dict] = []
        self._client = None

    def configure(self, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self._client = None

    def _get_client(self):
        if OpenAI is None:
            raise AIError("Не установлена библиотека openai: pip install openai")
        if not self.api_key:
            raise AIError("Не задан API-ключ OpenRouter. Откройте 'Настройки'.")
        if self._client is None:
            self._client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=90.0,
                max_retries=1,
                default_headers={
                    "HTTP-Referer": "https://github.com/loliksudoc/animetomogochi",
                    "X-Title": "ZetaBuddy",
                },
            )
        return self._client

    def clear_history(self) -> None:
        self.history.clear()

    def ask(self, question: str, context: str = "") -> AIReply:
        client = self._get_client()
        system = self.system_prompt
        if "[[open:" not in system:
            system += "\n\n" + TOOLS_PROMPT
        system += f"\n\nТекущее время: {datetime.now():%Y-%m-%d %H:%M}."
        if context:
            system += f"\n{context}"

        messages = [{"role": "system", "content": system}]
        messages += self.history[-self.history_length:]
        messages.append({"role": "user", "content": question})

        try:
            resp = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
            )
        except APITimeoutError:
            raise AIError("Сервер думает слишком долго. Попробуйте ещё раз.")
        except APIConnectionError:
            raise AIError("Нет соединения с OpenRouter. Проверьте интернет.")
        except APIStatusError as exc:
            raise AIError(self._status_message(exc))
        except Exception as exc:
            raise AIError(f"Ошибка запроса: {exc}")

        if not resp.choices:
            raise AIError("Модель вернула пустой ответ.")
        msg = resp.choices[0].message
        raw = msg.content or ""
        if not raw.strip():
            raw = getattr(msg, "reasoning", None) or ""
        if not raw.strip():
            raise AIError("Модель вернула пустой ответ.")

        self.history.append({"role": "user", "content": question})
        self.history.append({"role": "assistant", "content": raw})
        self.history = self.history[-self.history_length * 2:]
        return parse_reply(raw)

    @staticmethod
    def _status_message(exc) -> str:
        code = getattr(exc, "status_code", None)
        detail = ""
        try:
            body = exc.response.json()
            detail = body.get("error", {}).get("message", "") or ""
        except Exception:
            pass
        hints = {
            401: "Неверный API-ключ OpenRouter.",
            402: "Недостаточно кредитов на OpenRouter.",
            404: "Модель не найдена - проверьте название в 'Настройках'.",
            429: "Слишком много запросов (лимит бесплатной модели). Подождите немного.",
        }
        base = hints.get(code, f"Ошибка API ({code}).")
        return f"{base} {detail}".strip()
