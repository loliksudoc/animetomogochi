from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "ZetaBuddy"
APP_SLOGAN = "Zeta Intelligence on Your Desktop"

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
SOUNDS_DIR = ASSETS_DIR / "sounds"
SPRITES_DIR = ASSETS_DIR / "sprites"
CONFIG_PATH = BASE_DIR / "config.json"
ENV_PATH = BASE_DIR / ".env"

DEFAULT_SYSTEM_PROMPT = (
    "Ты - Зета (ZetaBuddy), настольный AI-ассистент в образе девушки-офисного "
    "профессионала: строгий чёрный костюм, синие очки, ярко-рыжие волосы. "
    "Ты умная, собранная и полезная, с лёгкой деловой иронией - но никогда не "
    "грубишь. Отвечай кратко и по делу (обычно 1-5 предложений), на языке "
    "пользователя. Избегай тяжёлой markdown-разметки: ответ показывается в "
    "маленьком облачке над твоей головой."
)

TOOLS_PROMPT = (
    "Ты умеешь запускать программы и управлять активным окном пользователя. "
    "Когда пользователь просит это сделать, добавь в конец ответа команды строго "
    "в указанном формате (пользователь их не видит).\n"
    "Открыть приложение, игру, сайт, папку или раздел настроек Windows по названию: "
    "[[open:НАЗВАНИЕ]], например [[open:telegram]], [[open:youtube]], [[open:загрузки]], "
    "[[open:steam]], [[open:диспетчер задач]], [[open:bluetooth]]. Можно несколько команд. "
    "Если пользователь описывает цель ('хочу послушать музыку', 'нужно посчитать'), "
    "выбери подходящее: [[open:музыка]], [[open:калькулятор]].\n"
    "Управление активным окном - [[window:ДЕЙСТВИЕ]]:\n"
    "  [[window:minimize]] - свернуть\n"
    "  [[window:maximize]] - развернуть\n"
    "  [[window:restore]] - восстановить\n"
    "  [[window:center]] - по центру экрана\n"
    "  [[window:snap_left]] / [[window:snap_right]] - на левую/правую половину\n"
    "  [[window:push_left]] / [[window:push_right]] - толкнуть окно в сторону\n"
    "  [[window:move:X,Y]] - переместить левый верхний угол в X,Y (пиксели)\n"
    "  [[window:resize:W,H]] - изменить размер окна\n"
    "Также можешь выразить эмоцию: [[emote:wave]], [[emote:jump]], "
    "[[emote:heart]], [[emote:shy]]. Команды пользователю не видны. "
    "Не используй команды, если пользователь о них не просил (эмоции - можно)."
)

DEFAULTS: dict = {
    "api_key": "",
    "base_url": "https://openrouter.ai/api/v1",
    "model": "nex-agi/nex-n2.5-pro:free",
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "temperature": 0.7,
    "history_length": 12,
    "voice_enabled": True,
    "sfx_enabled": True,
    "volume": 0.6,
    "scale": 3,
    "walk_enabled": True,
    "walk_speed": 1.6,
    "physics_mode": "floor",
    "activity": 0.5,
    "hotkey_enabled": True,
    "typing_speed_ms": 22,
}

AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _autostart_command() -> str:
    import sys
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    return f'"{pythonw if pythonw.exists() else exe}" "{BASE_DIR / "ZetaBuddy.pyw"}"'


def is_autostart_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except (ImportError, OSError):
        return False


def set_autostart(enabled: bool) -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except (ImportError, OSError) as exc:
        print(f"[config] Автозапуск: {exc}")
        return False


def load_env_file(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class Config:
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        self.data: dict = dict(DEFAULTS)
        load_env_file()
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
                self.data.update({k: v for k, v in stored.items() if k in DEFAULTS})
                marker = "Ты умеешь управлять активным окном пользователя."
                prompt = self.data.get("system_prompt", "")
                if marker in prompt:
                    self.data["system_prompt"] = prompt.split(marker)[0].rstrip() or DEFAULT_SYSTEM_PROMPT
            except (OSError, json.JSONDecodeError) as exc:
                print(f"[config] Не удалось прочитать {self.path}: {exc}")

    def save(self) -> None:
        try:
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            print(f"[config] Не удалось сохранить {self.path}: {exc}")

    def get(self, key: str):
        return self.data.get(key, DEFAULTS.get(key))

    def set(self, key: str, value) -> None:
        self.data[key] = value

    @property
    def api_key(self) -> str:
        return (self.data.get("api_key") or os.environ.get("OPENROUTER_API_KEY", "")).strip()
