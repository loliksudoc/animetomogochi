from __future__ import annotations

import signal
import sys
import tempfile
from pathlib import Path

from config import APP_NAME, APP_SLOGAN, BASE_DIR, Config


def setup_logging() -> None:
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_path = BASE_DIR / "zetabuddy.log"
    try:
        if log_path.exists() and log_path.stat().st_size > 1_000_000:
            log_path.unlink()
        log = open(log_path, "a", encoding="utf-8", buffering=1)
    except OSError:
        return
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log


setup_logging()

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from mascot_ui import MENU_STYLE, BuddyController

VK_OEM_5 = 0xDC
SCAN_BACKSLASH = 43


class HotkeyListener(QObject):
    triggered = Signal()

    def __init__(self):
        super().__init__()
        self._listener = None
        self._down = False
        self.backend: str | None = None

    @staticmethod
    def _is_hotkey(key) -> bool:
        if getattr(key, "vk", None) == VK_OEM_5:
            return True
        return getattr(key, "char", None) in ("\\", "|")

    def _press(self):
        if not self._down:
            self._down = True
            self.triggered.emit()

    def _release(self):
        self._down = False

    def start(self) -> bool:
        if self.backend:
            return True
        try:
            from pynput import keyboard

            self._listener = keyboard.Listener(
                on_press=lambda k: self._press() if self._is_hotkey(k) else None,
                on_release=lambda k: self._release() if self._is_hotkey(k) else None,
            )
            self._listener.daemon = True
            self._listener.start()
            self.backend = "pynput"
            return True
        except Exception as exc:
            print(f"[hotkey] pynput недоступен: {exc}")
        try:
            import keyboard as kb

            kb.on_press_key(SCAN_BACKSLASH, lambda e: self._press())
            kb.on_release_key(SCAN_BACKSLASH, lambda e: self._release())
            self.backend = "keyboard"
            return True
        except Exception as exc:
            print(f"[hotkey] keyboard недоступен: {exc}")
        return False

    def stop(self) -> None:
        if self.backend == "pynput" and self._listener:
            self._listener.stop()
        elif self.backend == "keyboard":
            try:
                import keyboard as kb
                kb.unhook_all()
            except Exception:
                pass
        self.backend = None


def build_tray(app: QApplication, ctrl: BuddyController) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(ctrl.mascot.app_icon(), app)
    tray.setToolTip(f"{APP_NAME} - {APP_SLOGAN}")
    menu = QMenu()
    menu.setStyleSheet(MENU_STYLE)
    menu.addAction("Показать / скрыть  ( \\ )", ctrl.toggle_visible)
    menu.addAction("Поговорить", lambda: (ctrl.mascot.isVisible() or ctrl.toggle_visible(), ctrl.open_chat()))
    menu.addAction("Настройки", ctrl.open_settings)
    menu.addSeparator()
    menu.addAction("Выход", ctrl.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: ctrl.toggle_visible()
        if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray._menu = menu
    tray.show()
    return tray


def main() -> int:
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    lock = QLockFile(str(Path(tempfile.gettempdir()) / "zetabuddy.lock"))
    if not lock.tryLock(100):
        print("ZetaBuddy уже запущен.")
        return 0

    cfg = Config()
    ctrl = BuddyController(cfg)
    app.setWindowIcon(ctrl.mascot.app_icon())

    hotkey = HotkeyListener()
    hotkey.triggered.connect(ctrl.on_hotkey)
    if cfg.get("hotkey_enabled"):
        hotkey.start()
    ctrl.hotkey_setting_changed.connect(lambda on: hotkey.start() if on else None)

    tray = build_tray(app, ctrl) if QSystemTrayIcon.isSystemTrayAvailable() else None
    ctrl.start()

    code = app.exec()
    hotkey.stop()
    if tray:
        tray.hide()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
