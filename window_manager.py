from __future__ import annotations

import os
import sys
from dataclasses import dataclass

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi")

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HMONITOR

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]

SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE = 3, 6, 9
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10
MONITOR_DEFAULTTONEAREST = 2
DWMWA_EXTENDED_FRAME_BOUNDS = 9

IGNORED_CLASSES = {
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "NotifyIconOverflowWindow", "Windows.UI.Core.CoreWindow", "TopLevelWindowForOverflowXamlIsland",
}


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h


class WindowManager:
    def __init__(self):
        self.available = IS_WINDOWS
        self._own_pid = os.getpid()
        self.last_external: int | None = None

    def foreground(self) -> int | None:
        if not self.available:
            return None
        hwnd = user32.GetForegroundWindow()
        return int(hwnd) if hwnd else None

    def track_foreground(self) -> int | None:
        hwnd = self.foreground()
        if hwnd and self.is_manageable(hwnd):
            self.last_external = hwnd
        if self.last_external and not self.is_window(self.last_external):
            self.last_external = None
        return self.last_external

    def target(self) -> int | None:
        return self.track_foreground()

    def is_window(self, hwnd: int) -> bool:
        return bool(self.available and hwnd and user32.IsWindow(hwnd))

    def is_manageable(self, hwnd: int) -> bool:
        if not self.is_window(hwnd) or not user32.IsWindowVisible(hwnd):
            return False
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == self._own_pid:
            return False
        return self.class_name(hwnd) not in IGNORED_CLASSES and bool(self.title(hwnd))

    def title(self, hwnd: int) -> str:
        if not self.is_window(hwnd):
            return ""
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def class_name(self, hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def rect(self, hwnd: int) -> Rect | None:
        if not self.is_window(hwnd):
            return None
        r = wintypes.RECT()
        res = dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS,
                                           ctypes.byref(r), ctypes.sizeof(r))
        if res != 0:
            user32.GetWindowRect(hwnd, ctypes.byref(r))
        return Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)

    def _frame_insets(self, hwnd: int) -> tuple[int, int, int, int]:
        outer = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(outer))
        vis = self.rect(hwnd)
        if vis is None:
            return 0, 0, 0, 0
        return (vis.x - outer.left, vis.y - outer.top,
                outer.right - vis.right, outer.bottom - vis.bottom)

    def work_area(self, hwnd: int) -> Rect | None:
        if not self.is_window(hwnd):
            return None
        mon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(mon, ctypes.byref(info)):
            return None
        w = info.rcWork
        return Rect(w.left, w.top, w.right - w.left, w.bottom - w.top)

    def is_minimized(self, hwnd: int) -> bool:
        return bool(self.is_window(hwnd) and user32.IsIconic(hwnd))

    def is_maximized(self, hwnd: int) -> bool:
        return bool(self.is_window(hwnd) and user32.IsZoomed(hwnd))

    def minimize(self, hwnd: int) -> bool:
        return self.is_window(hwnd) and bool(user32.ShowWindow(hwnd, SW_MINIMIZE) or True)

    def maximize(self, hwnd: int) -> bool:
        return self.is_window(hwnd) and bool(user32.ShowWindow(hwnd, SW_MAXIMIZE) or True)

    def restore(self, hwnd: int) -> bool:
        return self.is_window(hwnd) and bool(user32.ShowWindow(hwnd, SW_RESTORE) or True)

    def activate(self, hwnd: int) -> bool:
        return self.is_window(hwnd) and bool(user32.SetForegroundWindow(hwnd))

    def _normalize(self, hwnd: int) -> None:
        if self.is_minimized(hwnd) or self.is_maximized(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)

    def set_rect(self, hwnd: int, x: int, y: int, w: int | None = None, h: int | None = None) -> bool:
        if not self.is_window(hwnd):
            return False
        self._normalize(hwnd)
        l, t, r, b = self._frame_insets(hwnd)
        flags = SWP_NOZORDER | SWP_NOACTIVATE
        if w is None or h is None:
            flags |= SWP_NOSIZE
            w = h = 0
        else:
            w, h = max(160, int(w)) + l + r, max(90, int(h)) + t + b
        return bool(user32.SetWindowPos(hwnd, None, int(x) - l, int(y) - t, w, h, flags))

    def move(self, hwnd: int, x: int, y: int) -> bool:
        return self.set_rect(hwnd, x, y)

    def move_by(self, hwnd: int, dx: int, dy: int) -> bool:
        rc = self.rect(hwnd)
        return bool(rc) and self.set_rect(hwnd, rc.x + dx, rc.y + dy)

    def resize(self, hwnd: int, w: int, h: int) -> bool:
        rc = self.rect(hwnd)
        return bool(rc) and self.set_rect(hwnd, rc.x, rc.y, w, h)

    def center(self, hwnd: int) -> bool:
        self._normalize(hwnd)
        rc, wa = self.rect(hwnd), self.work_area(hwnd)
        if not rc or not wa:
            return False
        return self.set_rect(hwnd, wa.x + (wa.w - rc.w) // 2, wa.y + (wa.h - rc.h) // 2)

    def snap(self, hwnd: int, side: str) -> bool:
        self._normalize(hwnd)
        wa = self.work_area(hwnd)
        if not wa:
            return False
        half = wa.w // 2
        x = wa.x if side == "left" else wa.x + half
        return self.set_rect(hwnd, x, wa.y, half, wa.h)

    def clamp_position(self, hwnd: int, x: int, y: int) -> tuple[int, int]:
        rc, wa = self.rect(hwnd), self.work_area(hwnd)
        if not rc or not wa:
            return x, y
        margin = 80
        x = max(wa.x - rc.w + margin, min(x, wa.right - margin))
        y = max(wa.y, min(y, wa.bottom - margin))
        return x, y

    def describe(self, hwnd: int | None) -> str:
        if not hwnd or not self.is_window(hwnd):
            return "нет активного окна"
        rc = self.rect(hwnd)
        state = "свёрнуто" if self.is_minimized(hwnd) else "развёрнуто" if self.is_maximized(hwnd) else "обычное"
        geo = f"{rc.x},{rc.y} {rc.w}x{rc.h}" if rc else "?"
        return f"'{self.title(hwnd)[:80]}' ({state}, {geo})"
