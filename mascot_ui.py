from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

from PySide6.QtCore import (QElapsedTimer, QEvent, QObject, QPoint, QPointF, QRect,
                            QThread, QTimer, Qt, Signal)
from PySide6.QtGui import (QAction, QColor, QCursor, QGuiApplication, QIcon, QImage,
                           QPainter, QPixmap)
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QPlainTextEdit, QPushButton, QSlider,
                               QSpinBox, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

import sprites
from ai_client import AIClient, AIError, AIReply, Command
from app_launcher import AppLauncher, parse_open_command
from audio_manager import AudioManager
from config import (APP_NAME, APP_SLOGAN, DEFAULT_SYSTEM_PROMPT, SPRITES_DIR, Config,
                    is_autostart_enabled, set_autostart)
from window_manager import Rect, WindowManager

WINDOW_FLAGS = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool | Qt.WindowType.NoDropShadowWindowHint)

INK = "#1b1420"
PAPER = "#fffdf7"
BLUE = "#2b64e8"
RED = "#e0312b"

MENU_STYLE = f"""
QMenu {{ background:{PAPER}; border:2px solid {INK}; padding:4px; color:{INK};
        font: 10pt 'Segoe UI'; }}
QMenu::item {{ padding:6px 24px 6px 26px; }}
QMenu::item:selected {{ background:{BLUE}; color:white; }}
QMenu::item:disabled {{ color:#9a93a8; }}
QMenu::separator {{ height:2px; background:#e6e1ea; margin:4px 6px; }}
QMenu::indicator {{ width:12px; height:12px; left:6px; }}
"""


def screen_at(x: float, y: float):
    return (QGuiApplication.screenAt(QPoint(int(x), int(y)))
            or QGuiApplication.primaryScreen())


def _screen_for_physical(x: int, y: int):
    for s in QGuiApplication.screens():
        g, d = s.geometry(), s.devicePixelRatio()
        if g.x() <= x < g.x() + g.width() * d and g.y() <= y < g.y() + g.height() * d:
            return s
    return QGuiApplication.primaryScreen()


def phys_to_logical(x: int, y: int) -> tuple[float, float]:
    s = _screen_for_physical(x, y)
    g, d = s.geometry(), s.devicePixelRatio()
    return g.x() + (x - g.x()) / d, g.y() + (y - g.y()) / d


def dpr_at_physical(x: int, y: int) -> float:
    return _screen_for_physical(x, y).devicePixelRatio()


def ease(p: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, p)))


class SpriteBank:
    def __init__(self, scale: int):
        self.scale = scale
        self.frames: dict[str, list[tuple[QPixmap, QImage, int]]] = {}
        self.loops: dict[str, bool] = {}
        self.effects: dict[str, QPixmap] = {}
        cache: dict[sprites.Frame, QImage] = {}
        w, h = sprites.W * scale, sprites.H * scale

        for name, anim in sprites.ANIMATIONS.items():
            items = []
            for i, (frame, duration) in enumerate(anim["frames"]):
                img = self._custom(name, i, w, h)
                if img is None:
                    if frame not in cache:
                        cache[frame] = self._to_image(sprites.W, sprites.H,
                                                      sprites.render_rgba(sprites.compose(frame)))
                    img = cache[frame]
                items.append((QPixmap.fromImage(img), img, duration))
            self.frames[name] = items
            self.loops[name] = anim["loop"]

        for name in sprites.EFFECTS:
            ew, eh, data = sprites.effect_rgba(name)
            self.effects[name] = QPixmap.fromImage(self._to_image(ew, eh, data))

    def _to_image(self, w: int, h: int, data: bytes) -> QImage:
        img = QImage(data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
        return img.scaled(w * self.scale, h * self.scale,
                          Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.FastTransformation)

    @staticmethod
    def _custom(name: str, index: int, w: int, h: int) -> QImage | None:
        path = SPRITES_DIR / f"{name}_{index}.png"
        if not path.exists():
            return None
        img = QImage(str(path))
        if img.isNull():
            return None
        return img.convertToFormat(QImage.Format.Format_RGBA8888).scaled(
            w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)

    def icon(self) -> QIcon:
        pm = self.frames["idle"][0][0]
        s = self.scale
        head = pm.copy(0, 0, sprites.W * s, 27 * s)
        return QIcon(head.scaled(64, 54, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.FastTransformation))


class Animator:
    def __init__(self, bank: SpriteBank):
        self.bank = bank
        self.name = "idle"
        self.index = 0
        self.elapsed = 0.0
        self.finished = False

    def play(self, name: str, restart: bool = False) -> None:
        if name not in self.bank.frames:
            name = "idle"
        if name == self.name and not restart and not self.finished:
            return
        self.name, self.index, self.elapsed, self.finished = name, 0, 0.0, False

    def update(self, dt: float) -> None:
        frames = self.bank.frames[self.name]
        if self.finished:
            return
        self.elapsed += dt
        while self.elapsed >= frames[self.index][2]:
            self.elapsed -= frames[self.index][2]
            if self.index + 1 < len(frames):
                self.index += 1
            elif self.bank.loops[self.name]:
                self.index = 0
            else:
                self.finished = True
                self.elapsed = 0
                break

    @property
    def pixmap(self) -> QPixmap:
        return self.bank.frames[self.name][self.index][0]

    @property
    def image(self) -> QImage:
        return self.bank.frames[self.name][self.index][1]


@dataclass
class Particle:
    kind: str
    x: float
    y: float
    vx: float
    vy: float
    life: float
    delay: float = 0.0
    wobble: float = 0.0

    @property
    def max_life(self) -> float:
        return 1.0


def jump_offset(t: float, scale: int) -> float:
    if 130 <= t <= 550:
        return -math.sin(math.pi * (t - 130) / 420) * 20 * scale / 3
    return 0.0


class Task:
    started = False
    t = 0.0

    def update(self, m: "MascotWindow", dt: float) -> bool:
        raise NotImplementedError


class PoseTask(Task):
    def __init__(self, anim: str, duration: float, on_end=None, fx: str | None = None):
        self.anim, self.duration, self.on_end, self.fx = anim, duration, on_end, fx

    def update(self, m, dt):
        if not self.started:
            self.started = True
            m.anim.play(self.anim, restart=True)
        self.t += dt
        if self.t >= self.duration:
            if self.on_end:
                self.on_end()
            if self.fx:
                m.spawn(self.fx, 3)
            return True
        return False


class ReactTask(Task):
    def __init__(self, name: str, sound: bool = True):
        self.name, self.sound = name, sound

    def update(self, m, dt):
        if not self.started:
            self.started = True
            m.anim.play(self.name, restart=True)
            m.effects_for(self.name)
            if self.sound:
                m.audio.play_reaction(self.name)
        self.t += dt
        m.hop = jump_offset(self.t, m.scale) if self.name == "jump" else 0.0
        if m.anim.finished:
            m.hop = 0.0
            return True
        return False


class HopTask(Task):
    def __init__(self, target_fn, duration: float = 520):
        self.target_fn, self.duration = target_fn, duration

    def update(self, m, dt):
        if not self.started:
            self.started = True
            target = self.target_fn(m)
            if target is None:
                return True
            self.sx, self.sy = m.pos_x, m.pos_y
            self.tx, self.ty = target
            self.height = 36 * m.scale / 3 + max(0.0, self.sy - self.ty) * 0.2
            m.anim.play("hop", restart=True)
            m.audio.play_reaction("jump")
        self.t += dt
        p = min(1.0, self.t / self.duration)
        m.pos_x = self.sx + (self.tx - self.sx) * p
        m.pos_y = self.sy + (self.ty - self.sy) * p - math.sin(math.pi * p) * self.height
        return p >= 1.0


class WindowAnimTask(Task):
    def __init__(self, wm: WindowManager, hwnd: int, target_fn, duration: float = 420):
        self.wm, self.hwnd, self.target_fn, self.duration = wm, hwnd, target_fn, duration

    def update(self, m, dt):
        wm, hwnd = self.wm, self.hwnd
        if not self.started:
            self.started = True
            if not wm.is_window(hwnd):
                return True
            if wm.is_minimized(hwnd) or wm.is_maximized(hwnd):
                wm.restore(hwnd)
            self.start, wa = wm.rect(hwnd), wm.work_area(hwnd)
            if not self.start or not wa:
                return True
            self.target = self.target_fn(self.start, wa)
            self.resize = (self.target.w, self.target.h) != (self.start.w, self.start.h)
            m.anim.play("push", restart=True)
        self.t += dt
        p = ease(self.t / self.duration)
        s, e = self.start, self.target
        x = s.x + (e.x - s.x) * p
        y = s.y + (e.y - s.y) * p
        if self.resize:
            wm.set_rect(hwnd, x, y, s.w + (e.w - s.w) * p, s.h + (e.h - s.h) * p)
        else:
            wm.set_rect(hwnd, x, y)
        if self.t >= self.duration:
            m.spawn("sparkle", 2)
            return True
        return False


class PushWindowTask(Task):
    def __init__(self, wm: WindowManager, hwnd: int, direction: int,
                 duration: float = 1300, speed: float = 7.0):
        self.wm, self.hwnd, self.d = wm, hwnd, direction
        self.duration, self.speed, self.acc = duration, speed, 0.0

    def update(self, m, dt):
        wm, hwnd = self.wm, self.hwnd
        if not self.started:
            self.started = True
            m.anim.play("push", restart=True)
        rc, wa = wm.rect(hwnd), wm.work_area(hwnd)
        if not rc or not wa:
            return True
        self.t += dt
        self.acc += self.d * self.speed * dt / 16
        step = int(self.acc)
        self.acc -= step
        step = min(step, wa.right - rc.right) if self.d > 0 else max(step, wa.x - rc.x)
        blocked = (self.d > 0 and rc.right >= wa.right) or (self.d < 0 and rc.x <= wa.x)
        if step:
            wm.set_rect(hwnd, rc.x + step, rc.y)
            m.pos_x += step / dpr_at_physical(rc.x + rc.w // 2, rc.y + rc.h // 2)
            m.clamp_to_screen()
        if blocked:
            m.spawn("sweat", 1)
            m.audio.play_reaction("surprised")
            return True
        return self.t >= self.duration


class MascotWindow(QWidget):
    clicked = Signal()
    menu_requested = Signal(QPoint)
    moved = Signal()

    def __init__(self, cfg: Config, audio: AudioManager):
        super().__init__(None, WINDOW_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle(APP_NAME)
        self.cfg, self.audio = cfg, audio

        self.scale = int(cfg.get("scale"))
        self.bank = SpriteBank(self.scale)
        self.anim = Animator(self.bank)
        self._compute_sizes()

        self.pos_x, self.pos_y = 400.0, 400.0
        self.vx = self.vy = 0.0
        self.hop = 0.0
        self.angle = 0.0
        self.state, self.state_time = "idle", 0.0
        self.idle_left = 2500.0
        self.pose_left: float | None = None
        self.walk_target = (0.0, 0.0, False)
        self.bounced = False
        self.busy: str | None = None
        self.hold_still = False
        self.tasks: list[Task] = []
        self.particles: list[Particle] = []
        self.last_reaction = ""
        self.last_interaction = time.monotonic()
        self.fx_timer = 0.0
        self._last_xy: tuple[int, int] | None = None

        self.press_global: QPointF | None = None
        self.grab_offset = (0.0, 0.0)
        self.grab_local = QPointF()
        self.drag_v = (0.0, 0.0)
        self._drag_clock = QElapsedTimer()

        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)

    def _compute_sizes(self) -> None:
        s = self.scale
        self.sw, self.sh = sprites.W * s, sprites.H * s
        self.mx, self.mt, self.mb = 14 * s, 20 * s, 5 * s
        self.setFixedSize(self.sw + 2 * self.mx, self.mt + self.sh + self.mb)

    def set_scale(self, scale: int) -> None:
        if scale == self.scale:
            return
        self.scale = scale
        name = self.anim.name
        self.bank = SpriteBank(scale)
        self.anim.bank = self.bank
        self.anim.play(name, restart=True)
        self._compute_sizes()
        self._last_xy = None
        self._apply_geometry()

    def app_icon(self) -> QIcon:
        return self.bank.icon()

    def _geo(self) -> QRect:
        return screen_at(self.pos_x, self.pos_y - self.sh / 2).availableGeometry()

    def floor(self) -> float:
        g = self._geo()
        return float(g.y() + g.height())

    def bounds(self) -> tuple[float, float, float, float]:
        g = self._geo()
        half = self.sw * 0.4
        return (g.x() + half, g.x() + g.width() - half,
                g.y() + self.sh + 4 * self.scale, g.y() + g.height())

    def clamp_to_screen(self) -> None:
        l, r, t, b = self.bounds()
        self.pos_x = max(l, min(r, self.pos_x))
        self.pos_y = max(t, min(b, self.pos_y))

    def head_anchor(self) -> QPoint:
        return QPoint(int(self.pos_x), int(self.pos_y - self.sh + self.hop))

    def place_at(self, x: float, y: float) -> None:
        self.pos_x, self.pos_y = x, y
        self._apply_geometry()

    def _apply_geometry(self) -> None:
        xy = (round(self.pos_x - self.width() / 2), round(self.pos_y - self.mt - self.sh))
        if xy != self._last_xy:
            self._last_xy = xy
            self.move(*xy)
            self.moved.emit()

    def showEvent(self, e):
        self.clock.start()
        self.timer.start(16)
        super().showEvent(e)

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)

    def _set_state(self, state: str) -> None:
        self.state, self.state_time = state, 0.0

    def _tick(self) -> None:
        dt = float(min(50, self.clock.restart()))
        self.anim.update(dt)
        self.state_time += dt
        getattr(self, f"_st_{self.state}")(dt)
        self._update_particles(dt)
        target_angle = 0.0
        if self.state == "drag":
            target_angle = max(-28.0, min(28.0, -self.drag_v[0] * 32))
        self.angle += (target_angle - self.angle) * min(1.0, dt / 90)
        self._apply_geometry()
        self.update()

    def touch(self) -> None:
        self.last_interaction = time.monotonic()
        if self.state == "sleep":
            self._set_state("idle")

    def set_busy(self, busy: str | None) -> None:
        self.busy = busy
        if busy and self.state in ("walk", "pose", "sleep"):
            self._set_state("idle")

    def set_hold_still(self, hold: bool) -> None:
        self.hold_still = hold
        if hold and self.state in ("walk", "sleep"):
            self._set_state("idle")

    def react(self, name: str | None = None, sound: bool = True) -> str:
        if name is None:
            choices = [r for r in sprites.REACTIONS if r != self.last_reaction]
            name = random.choice(choices)
        self.last_reaction = name
        if self.state == "task":
            self.tasks.append(ReactTask(name, sound))
            return name
        if self.state in ("drag", "fall"):
            return name
        self._set_state("react")
        self.anim.play(name, restart=True)
        self.effects_for(name)
        if sound:
            self.audio.play_reaction(name)
        return name

    def run_tasks(self, tasks: list[Task]) -> None:
        if not tasks or self.state == "drag":
            return
        self.hop = 0.0
        self.tasks.extend(tasks)
        if self.state != "task":
            self._set_state("task")

    def cancel_tasks(self) -> None:
        self.tasks.clear()

    def effects_for(self, name: str) -> None:
        mapping = {"jump": ("sparkle", 3), "wave": ("note", 2), "heart": ("heart", 3),
                   "shy": ("sweat", 1), "surprised": ("excl", 1)}
        if name in mapping:
            self.spawn(*mapping[name])

    def spawn(self, kind: str, count: int = 1) -> None:
        s = self.scale / 3
        cx = self.mx + self.sw / 2
        top = self.mt + 6 * self.scale
        for i in range(count):
            if kind == "heart":
                p = Particle(kind, cx + random.uniform(-26, 26) * s, top, random.uniform(-0.02, 0.02),
                             -0.07 * s, 1300, delay=i * 260, wobble=random.uniform(0, 6))
            elif kind == "note":
                p = Particle(kind, cx + (40 if i % 2 else -40) * s, top + 10 * s,
                             (0.03 if i % 2 else -0.03) * s, -0.06 * s, 1100, delay=i * 300)
            elif kind == "sweat":
                p = Particle(kind, cx + 34 * s, top + 16 * s, 0.01 * s, 0.03 * s, 1000)
            elif kind == "excl":
                p = Particle(kind, cx + 30 * s, top - 10 * s, 0, -0.01 * s, 900)
            elif kind == "z":
                p = Particle(kind, cx + 22 * s, top, 0.025 * s, -0.04 * s, 1600, wobble=random.uniform(0, 6))
            elif kind == "question":
                p = Particle(kind, cx + 30 * s, top - 6 * s, 0, -0.015 * s, 1500)
            else:
                p = Particle(kind, cx + random.uniform(-45, 45) * s, top + random.uniform(-10, 40) * s,
                             0, -0.02 * s, 700, delay=i * 120)
            self.particles.append(p)

    def _update_particles(self, dt: float) -> None:
        alive = []
        for p in self.particles:
            if p.delay > 0:
                p.delay -= dt
                alive.append(p)
                continue
            p.life -= dt
            p.x += p.vx * dt + (math.sin(p.life / 180 + p.wobble) * 0.15 if p.kind in ("heart", "z") else 0)
            p.y += p.vy * dt
            if p.life > 0:
                alive.append(p)
        self.particles = alive

        if self.state == "sleep":
            self.fx_timer += dt
            if self.fx_timer > 1300:
                self.fx_timer = 0
                self.spawn("z")

    def _idle_anim(self) -> str:
        return {"think": "think", "talk": "talk"}.get(self.busy or "", "idle")

    def _is_floor_mode(self) -> bool:
        return self.cfg.get("physics_mode") != "free"

    def _needs_fall(self) -> bool:
        return self._is_floor_mode() and self.pos_y < self.floor() - 1

    def _st_idle(self, dt):
        self.anim.play(self._idle_anim())
        if self._needs_fall():
            self._start_fall()
            return
        if self.busy or self.hold_still:
            return
        self.idle_left -= dt
        if self.idle_left <= 0:
            self._decide()

    def _rand_idle(self) -> float:
        activity = float(self.cfg.get("activity"))
        return random.uniform(2500, 7000) * (1.4 - activity)

    def _decide(self) -> None:
        idle_for = time.monotonic() - self.last_interaction
        if idle_for > 120 and random.random() < 0.3:
            self._set_state("sleep")
            self.anim.play("sleep", restart=True)
            return
        activity = float(self.cfg.get("activity"))
        if self.cfg.get("walk_enabled") and random.random() < 0.25 + 0.5 * activity:
            self._start_walk()
            return
        r = random.random()
        if r < 0.25:
            self._start_pose("idle_back", random.uniform(1800, 3200))
        elif r < 0.33:
            self._start_pose("wave")
        else:
            self.idle_left = self._rand_idle()

    def _start_pose(self, anim: str, duration: float | None = None) -> None:
        self._set_state("pose")
        self.anim.play(anim, restart=True)
        self.pose_left = duration

    def _st_pose(self, dt):
        if self.pose_left is not None:
            self.pose_left -= dt
            done = self.pose_left <= 0
        else:
            done = self.anim.finished
        if done:
            self._set_state("idle")
            self.idle_left = self._rand_idle()

    def _start_walk(self) -> None:
        l, r, t, b = self.bounds()
        edge = random.random() < 0.22
        if edge:
            tx = l if random.random() < 0.5 else r
        else:
            tx = random.uniform(l, r)
            if abs(tx - self.pos_x) < 60:
                tx = l + (r - l) * random.random()
        if self._is_floor_mode():
            ty = b
        else:
            ty = self.pos_y if edge else random.uniform(t, b)
        self.walk_target = (tx, ty, edge)
        self._set_state("walk")

    def _st_walk(self, dt):
        if self.busy or self.hold_still:
            self._set_state("idle")
            return
        tx, ty, edge = self.walk_target
        dx, dy = tx - self.pos_x, ty - self.pos_y
        dist = math.hypot(dx, dy)
        speed = float(self.cfg.get("walk_speed")) * (self.scale / 3) * dt / 16
        if dist <= speed:
            self.pos_x, self.pos_y = tx, ty
            if edge:
                self._edge_reaction()
            else:
                self._set_state("idle")
                self.idle_left = self._rand_idle()
            return
        self.pos_x += dx / dist * speed
        self.pos_y += dy / dist * speed
        if not self._is_floor_mode() and abs(dy) > abs(dx) * 1.2:
            self.anim.play("walk_back" if dy < 0 else "walk_front")
        else:
            self.anim.play("walk_right" if dx > 0 else "walk_left")

    def _edge_reaction(self) -> None:
        if random.random() < 0.5:
            self.react("surprised", sound=bool(self.cfg.get("sfx_enabled")))
            self.spawn("sweat")
        else:
            self._start_pose("idle_back", 2200)

    def _start_fall(self, vx: float = 0.0, vy: float = 0.0) -> None:
        self._set_state("fall")
        self.vx, self.vy, self.bounced = vx, vy, False
        self.anim.play("fall", restart=True)

    def _st_fall(self, dt):
        self.vy = min(self.vy + 0.0032 * dt, 2.4)
        self.vx *= 0.9985 ** dt
        self.pos_x += self.vx * dt
        self.pos_y += self.vy * dt
        l, r, _, _ = self.bounds()
        if self.pos_x < l or self.pos_x > r:
            self.pos_x = max(l, min(r, self.pos_x))
            self.vx = -self.vx * 0.4
        floor = self.floor()
        if self.pos_y >= floor:
            self.pos_y = floor
            if self.vy > 1.1 and not self.bounced:
                self.bounced = True
                self.vy, self.vx = -self.vy * 0.25, self.vx * 0.5
                self.audio.play_reaction("surprised")
            else:
                self.vx = self.vy = 0.0
                self._start_pose("land")

    def _st_react(self, dt):
        self.hop = jump_offset(self.state_time, self.scale) if self.anim.name == "jump" else 0.0
        if self.anim.finished:
            self.hop = 0.0
            self._set_state("idle")
            self.idle_left = max(self.idle_left, 2500)

    def _st_sleep(self, dt):
        self.anim.play("sleep")
        if self._needs_fall():
            self._start_fall()

    def _st_task(self, dt):
        if not self.tasks:
            self.hop = 0.0
            if self._needs_fall():
                self._start_fall()
            else:
                self._set_state("idle")
                self.idle_left = self._rand_idle()
            return
        try:
            done = self.tasks[0].update(self, dt)
        except Exception as exc:
            print(f"[mascot] task error: {exc}")
            done = True
        if done and self.tasks:
            self.tasks.pop(0)

    def _st_drag(self, dt):
        self.anim.play("drag")

    def _opaque_at(self, pt: QPointF) -> bool:
        img = self.anim.image
        x = int(pt.x() - self.mx)
        y = int(pt.y() - self.mt - self.hop)
        r = self.scale * 2
        for yy in (y - r, y, y + r):
            for xx in (x - r, x, x + r):
                if 0 <= xx < img.width() and 0 <= yy < img.height() and img.pixelColor(xx, yy).alpha() > 0:
                    return True
        return False

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if not self._opaque_at(e.position()):
                e.ignore()
                return
            g = e.globalPosition()
            self.press_global = g
            self.grab_offset = (g.x() - self.pos_x, g.y() - self.pos_y)
            self.grab_local = e.position()
            self.drag_v = (0.0, 0.0)
            self._drag_clock.start()
            self.touch()
        elif e.button() == Qt.MouseButton.RightButton:
            self.touch()
            self.menu_requested.emit(e.globalPosition().toPoint())

    def mouseDoubleClickEvent(self, e):
        self.mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.press_global is None or not (e.buttons() & Qt.MouseButton.LeftButton):
            return
        g = e.globalPosition()
        if self.state != "drag":
            if (g - self.press_global).manhattanLength() < 6:
                return
            self.cancel_tasks()
            self.hop = 0.0
            self._set_state("drag")
            self.anim.play("drag", restart=True)
            self.audio.play_reaction("click")
        nx, ny = g.x() - self.grab_offset[0], g.y() - self.grab_offset[1]
        elapsed = max(1, self._drag_clock.restart())
        vx = (nx - self.pos_x) / elapsed
        vy = (ny - self.pos_y) / elapsed
        self.drag_v = (self.drag_v[0] * 0.6 + vx * 0.4, self.drag_v[1] * 0.6 + vy * 0.4)
        self.pos_x, self.pos_y = nx, ny
        self._apply_geometry()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self.press_global is None:
            return
        self.press_global = None
        if self.state == "drag":
            if self._is_floor_mode():
                vx = max(-2.0, min(2.0, self.drag_v[0]))
                vy = max(-1.6, min(1.2, self.drag_v[1]))
                self._start_fall(vx, vy)
            else:
                self.clamp_to_screen()
                self._start_pose("land")
        else:
            self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        sx, sy = self.mx, self.mt + self.hop
        if abs(self.angle) > 0.3:
            pivot = self.grab_local if self.state == "drag" else QPointF(sx + self.sw / 2, sy)
            p.translate(pivot)
            p.rotate(self.angle)
            p.translate(-pivot)
        p.drawPixmap(int(sx), int(sy), self.anim.pixmap)
        p.resetTransform()

        for part in self.particles:
            if part.delay > 0:
                continue
            pm = self.bank.effects.get(part.kind)
            if pm is None:
                continue
            p.setOpacity(max(0.0, min(1.0, part.life / 350)))
            p.drawPixmap(int(part.x - pm.width() / 2), int(part.y - pm.height() / 2), pm)
        p.setOpacity(1.0)

        if self.busy == "think":
            dot = self.bank.effects["dot"]
            n = int(self.state_time / 350) % 4
            cx = self.mx + self.sw / 2 - 6 * self.scale
            for i in range(n):
                p.drawPixmap(int(cx + i * 5 * self.scale), int(self.mt - 1 * self.scale), dot)
        p.end()


BUBBLE_STYLE = f"""
QLabel#title {{ color:{INK}; font: 700 10pt 'Segoe UI'; }}
QLabel#slogan {{ color:#8a8398; font: 8pt 'Segoe UI'; }}
QTextBrowser {{ background: transparent; border: none; color:{INK}; font: 10pt 'Segoe UI';
               selection-background-color:{BLUE}; }}
QLineEdit {{ background:#ffffff; border:2px solid {INK}; padding:5px 6px; color:{INK};
            font: 10pt 'Segoe UI'; selection-background-color:{BLUE}; }}
QLineEdit:focus {{ border-color:{BLUE}; }}
QPushButton#send {{ background:{BLUE}; color:white; border:2px solid {INK}; padding:4px 10px;
                   font: 700 11pt 'Segoe UI'; }}
QPushButton#send:hover {{ background:#3d75f5; }}
QPushButton#send:disabled {{ background:#a9bcec; }}
QPushButton#icon {{ background: transparent; border:none; color:#6b6478; font: 11pt 'Segoe UI';
                   padding: 0 4px; }}
QPushButton#icon:hover {{ color:{RED}; }}
QCheckBox {{ color:#4a4458; font: 9pt 'Segoe UI'; spacing: 4px; }}
QScrollBar:vertical {{ background: transparent; width: 6px; margin: 0; }}
QScrollBar::handle:vertical {{ background:#cfc8d8; min-height: 20px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


class ChatBubble(QWidget):
    submitted = Signal(str)
    voice_toggled = Signal(bool)
    clear_requested = Signal()
    closed = Signal()
    typing_tick = Signal()
    typing_finished = Signal()

    P = 3
    TAIL = 16

    def __init__(self, voice_enabled: bool, typing_speed_ms: int = 22):
        super().__init__(None, WINDOW_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(f"{APP_NAME} - чат")
        self.setFixedWidth(350)
        self.setStyleSheet(BUBBLE_STYLE)
        self.tail_x, self.tail_visible = 175, True
        self.busy = False
        self._full, self._shown = "", 0
        self._anchor: QPoint | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12 + self.TAIL)
        root.setSpacing(6)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel(APP_NAME)
        title.setObjectName("title")
        slogan = QLabel(APP_SLOGAN)
        slogan.setObjectName("slogan")
        titles.addWidget(title)
        titles.addWidget(slogan)
        header.addLayout(titles)
        header.addStretch(1)
        self.voice_cb = QCheckBox("Озвучка")
        self.voice_cb.setChecked(voice_enabled)
        self.voice_cb.setToolTip("Озвучивать ответы")
        self.voice_cb.toggled.connect(self.voice_toggled)
        header.addWidget(self.voice_cb)
        clear_btn = QPushButton("⟲")
        clear_btn.setObjectName("icon")
        clear_btn.setToolTip("Новый диалог")
        clear_btn.clicked.connect(self.clear_requested)
        close_btn = QPushButton("✕")
        close_btn.setObjectName("icon")
        close_btn.setToolTip("Закрыть (Esc)")
        close_btn.clicked.connect(self.close_bubble)
        header.addWidget(clear_btn)
        header.addWidget(close_btn)
        root.addLayout(header)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.viewport().installEventFilter(self)
        root.addWidget(self.view)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Спросите Зету...  (/help - команды)")
        self.input.returnPressed.connect(self._submit)
        self.input.textEdited.connect(lambda _: self._restart_autohide())
        self.send_btn = QPushButton("➤")
        self.send_btn.setObjectName("send")
        self.send_btn.clicked.connect(self._submit)
        row.addWidget(self.input, 1)
        row.addWidget(self.send_btn)
        root.addLayout(row)

        self.type_timer = QTimer(self)
        self.type_timer.timeout.connect(self._type_step)
        self.typing_speed_ms = typing_speed_ms
        self.think_timer = QTimer(self)
        self.think_timer.timeout.connect(self._think_step)
        self._think_n = 0
        self.autohide = QTimer(self)
        self.autohide.setSingleShot(True)
        self.autohide.timeout.connect(self._maybe_autohide)

        self._set_view_text("", plain=True)

    def open_at(self, anchor: QPoint, focus: bool = True) -> None:
        self.reposition(anchor)
        self.show()
        self.raise_()
        if focus:
            self.activateWindow()
            self.input.setFocus()
        self._restart_autohide()

    def close_bubble(self) -> None:
        self.hide()
        self.closed.emit()

    def reposition(self, anchor: QPoint | None = None) -> None:
        if anchor is not None:
            self._anchor = anchor
        if self._anchor is None:
            return
        a = self._anchor
        geo = screen_at(a.x(), a.y()).availableGeometry()
        self.adjustSize()
        w, h = self.width(), self.height()
        x = max(geo.x() + 4, min(a.x() - w // 2, geo.x() + geo.width() - w - 4))
        y = a.y() - h + 4
        self.tail_visible = y >= geo.y() + 4
        y = max(geo.y() + 4, y)
        self.tail_x = max(24, min(w - 24, a.x() - x))
        self.move(x, y)
        self.update()

    def _set_view_text(self, text: str, plain: bool = False, html: bool = False) -> None:
        if html:
            self.view.setHtml(text)
        elif plain:
            self.view.setPlainText(text)
        else:
            self.view.setMarkdown(text)
        doc = self.view.document()
        doc.setTextWidth(self.view.viewport().width() or 300)
        height = int(doc.size().height()) + 6
        self.view.setFixedHeight(max(26, min(230, height)))
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())
        self.reposition()

    def type_text(self, text: str) -> None:
        self.think_timer.stop()
        self._full, self._shown = text, 0
        self.busy = True
        self.send_btn.setEnabled(False)
        self.type_timer.start(max(5, self.typing_speed_ms))
        self._restart_autohide()

    def finish_typing(self) -> None:
        if self.type_timer.isActive():
            self._shown = len(self._full)
            self._type_step()

    def _type_step(self) -> None:
        step = 1 if len(self._full) < 300 else 2 if len(self._full) < 900 else 4
        prev = self._shown
        self._shown = min(len(self._full), self._shown + step)
        self._set_view_text(self._full[:self._shown], plain=True)
        chunk = self._full[prev:self._shown]
        if chunk.strip() and self._shown // step % 3 == 0:
            self.typing_tick.emit()
        if self._shown >= len(self._full):
            self.type_timer.stop()
            self._set_view_text(self._full)
            self.busy = False
            self.send_btn.setEnabled(True)
            self._restart_autohide()
            self.typing_finished.emit()

    def set_thinking(self) -> None:
        self.busy = True
        self.send_btn.setEnabled(False)
        self._think_n = 0
        self._think_step()
        self.think_timer.start(350)

    def _think_step(self) -> None:
        self._think_n = (self._think_n + 1) % 4
        self._set_view_text(f"<i style='color:#8a8398'>Зета думает{'.' * self._think_n}</i>", html=True)

    def show_error(self, message: str) -> None:
        self.think_timer.stop()
        self.busy = False
        self.send_btn.setEnabled(True)
        self._set_view_text(f"<span style='color:{RED}'>{message}</span>", html=True)
        self._restart_autohide()

    def input_has_focus(self) -> bool:
        return self.isVisible() and self.isActiveWindow() and self.input.hasFocus()

    def _submit(self) -> None:
        text = self.input.text().strip()
        if not text or self.busy:
            return
        self.input.clear()
        self.submitted.emit(text)

    def _restart_autohide(self) -> None:
        self.autohide.start(35_000)

    def _maybe_autohide(self) -> None:
        if self.busy or self.input.text() or self.isActiveWindow() or self.underMouse():
            self._restart_autohide()
            return
        self.close_bubble()

    def eventFilter(self, obj, event):
        if obj is self.view.viewport() and event.type() == QEvent.Type.MouseButtonPress:
            self.finish_typing()
        return super().eventFilter(obj, event)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close_bubble()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        P = self.P
        ink, paper, shadow = QColor(INK), QColor(PAPER), QColor(0, 0, 0, 45)
        body = QRect(0, 0, self.width() - P, self.height() - self.TAIL)

        def box(r: QRect, outline: QColor, fill: QColor):
            x, y, w, h = r.x(), r.y(), r.width(), r.height()
            p.fillRect(x + 2 * P, y, w - 4 * P, h, outline)
            p.fillRect(x + P, y + P, w - 2 * P, h - 2 * P, outline)
            p.fillRect(x, y + 2 * P, w, h - 4 * P, outline)
            p.fillRect(x + 2 * P, y + P, w - 4 * P, h - 2 * P, fill)
            p.fillRect(x + P, y + 2 * P, w - 2 * P, h - 4 * P, fill)

        box(body.translated(P, P), shadow, shadow)
        box(body, ink, paper)
        p.fillRect(2 * P, P, (body.width() - 4 * P) // 2, P, QColor(RED))
        p.fillRect(2 * P + (body.width() - 4 * P) // 2, P, (body.width() - 4 * P) // 2, P, QColor(BLUE))

        if self.tail_visible:
            tx = self.tail_x - self.tail_x % P
            by = body.bottom() + 1 - P
            for i in range(5):
                half = (4 - i) * P
                y = by + i * P
                p.fillRect(tx - half - P, y, 2 * half + 2 * P, P, ink)
                if half:
                    p.fillRect(tx - half, y, 2 * half, P, paper)
        p.end()


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle(f"{APP_NAME} - Настройки")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(460)

        tabs = QTabWidget()

        ai = QWidget()
        form = QFormLayout(ai)
        self.api_key = QLineEdit(cfg.data.get("api_key", ""))
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        if not cfg.data.get("api_key") and cfg.api_key:
            self.api_key.setPlaceholderText("используется ключ из .env / OPENROUTER_API_KEY")
        show = QCheckBox("показать")
        show.toggled.connect(lambda on: self.api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        key_row = QHBoxLayout()
        key_row.addWidget(self.api_key, 1)
        key_row.addWidget(show)
        form.addRow("API-ключ:", key_row)
        self.base_url = QLineEdit(cfg.get("base_url"))
        form.addRow("Base URL:", self.base_url)
        self.model = QLineEdit(cfg.get("model"))
        form.addRow("Модель:", self.model)
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.1)
        self.temperature.setValue(float(cfg.get("temperature")))
        form.addRow("Температура:", self.temperature)
        self.history = QSpinBox()
        self.history.setRange(0, 50)
        self.history.setValue(int(cfg.get("history_length")))
        form.addRow("Память (реплик):", self.history)
        self.prompt = QPlainTextEdit(cfg.get("system_prompt"))
        self.prompt.setMinimumHeight(140)
        reset = QPushButton("Сбросить промпт")
        reset.clicked.connect(lambda: self.prompt.setPlainText(DEFAULT_SYSTEM_PROMPT))
        form.addRow("Системный промпт:", self.prompt)
        form.addRow("", reset)
        tabs.addTab(ai, "AI")

        snd = QWidget()
        form = QFormLayout(snd)
        self.voice = QCheckBox("Озвучивать ответы")
        self.voice.setChecked(bool(cfg.get("voice_enabled")))
        form.addRow(self.voice)
        self.sfx = QCheckBox("Звуки кликов и реакций")
        self.sfx.setChecked(bool(cfg.get("sfx_enabled")))
        form.addRow(self.sfx)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(int(float(cfg.get("volume")) * 100))
        form.addRow("Громкость:", self.volume)
        hint = QLabel("Голос: фразы <b>voice_*.wav</b> и реплики на клик <b>react_*.wav</b><br>"
                      "в папке <code>assets/sounds/voice</code>. Без них - <b>voice.mp3</b><br>"
                      "или 'бипы' <b>speech_sound.wav</b>. После замены перезапустите.")
        hint.setWordWrap(True)
        form.addRow(hint)
        tabs.addTab(snd, "Звук")

        ch = QWidget()
        form = QFormLayout(ch)
        self.scale = QSpinBox()
        self.scale.setRange(2, 8)
        self.scale.setValue(int(cfg.get("scale")))
        form.addRow("Размер (масштаб):", self.scale)
        self.physics = QComboBox()
        self.physics.addItem("По панели задач (гравитация)", "floor")
        self.physics.addItem("Свободно по всему экрану", "free")
        self.physics.setCurrentIndex(0 if cfg.get("physics_mode") != "free" else 1)
        form.addRow("Перемещение:", self.physics)
        self.walk = QCheckBox("Гулять по экрану")
        self.walk.setChecked(bool(cfg.get("walk_enabled")))
        form.addRow(self.walk)
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.3, 6.0)
        self.speed.setSingleStep(0.1)
        self.speed.setValue(float(cfg.get("walk_speed")))
        form.addRow("Скорость ходьбы:", self.speed)
        self.activity = QSlider(Qt.Orientation.Horizontal)
        self.activity.setRange(0, 100)
        self.activity.setValue(int(float(cfg.get("activity")) * 100))
        form.addRow("Активность:", self.activity)
        self.typing = QSpinBox()
        self.typing.setRange(5, 120)
        self.typing.setSuffix(" мс/символ")
        self.typing.setValue(int(cfg.get("typing_speed_ms")))
        form.addRow("Скорость печати:", self.typing)
        self.hotkey = QCheckBox("Горячая клавиша \\ (показать / скрыть)")
        self.hotkey.setChecked(bool(cfg.get("hotkey_enabled")))
        form.addRow(self.hotkey)
        self._autostart_was = is_autostart_enabled()
        self.autostart = QCheckBox("Запускать вместе с Windows (в фоне)")
        self.autostart.setChecked(self._autostart_was)
        form.addRow(self.autostart)
        tabs.addTab(ch, "Персонаж")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    def apply(self) -> None:
        c = self.cfg
        c.set("api_key", self.api_key.text().strip())
        c.set("base_url", self.base_url.text().strip() or "https://openrouter.ai/api/v1")
        c.set("model", self.model.text().strip())
        c.set("temperature", self.temperature.value())
        c.set("history_length", self.history.value())
        c.set("system_prompt", self.prompt.toPlainText().strip() or DEFAULT_SYSTEM_PROMPT)
        c.set("voice_enabled", self.voice.isChecked())
        c.set("sfx_enabled", self.sfx.isChecked())
        c.set("volume", self.volume.value() / 100)
        c.set("scale", self.scale.value())
        c.set("physics_mode", self.physics.currentData())
        c.set("walk_enabled", self.walk.isChecked())
        c.set("walk_speed", self.speed.value())
        c.set("activity", self.activity.value() / 100)
        c.set("typing_speed_ms", self.typing.value())
        c.set("hotkey_enabled", self.hotkey.isChecked())
        c.save()
        if self.autostart.isChecked() != self._autostart_was:
            set_autostart(self.autostart.isChecked())


class AIWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, client: AIClient, question: str, context: str):
        super().__init__()
        self.client, self.question, self.context = client, question, context

    def run(self):
        try:
            self.done.emit(self.client.ask(self.question, self.context))
        except AIError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Неожиданная ошибка: {exc}")


HELP_TEXT = """**Открыть что угодно:** 'открой телеграм', 'запусти кс и дискорд', 'вруби музыку',
'открой загрузки', 'открой настройки блютуз', 'открой ютуб' - приложения, игры, сайты, папки.
`/apps` - размер базы · `/apps refresh` - пересканировать программы · `/find X` - что найдётся

**Окна** (последнее активное окно):
`/min` свернуть · `/max` развернуть · `/restore` восстановить
`/center` по центру · `/left` `/right` половина экрана
`/push left` `/push right` - толкнуть окно
`/move X Y` · `/size W H`
`/wave` `/jump` `/heart` `/shy` - эмоции · `/clear` - новый диалог

Или просто попросите: 'сверни окно', 'подвинь окно вправо'."""

LOCAL_COMMANDS = {
    "min": ("window", "minimize"), "minimize": ("window", "minimize"),
    "max": ("window", "maximize"), "maximize": ("window", "maximize"),
    "restore": ("window", "restore"), "center": ("window", "center"),
    "left": ("window", "snap_left"), "right": ("window", "snap_right"),
    "push left": ("window", "push_left"), "push right": ("window", "push_right"),
    "move": ("window", "move"), "size": ("window", "resize"), "resize": ("window", "resize"),
    "wave": ("emote", "wave"), "jump": ("emote", "jump"),
    "heart": ("emote", "heart"), "shy": ("emote", "shy"),
}


OPEN_PHRASES = ["Открываю {}.", "Запускаю {} - секунду.", "{} уже в пути.",
                "Готово: {}.", "Сейчас будет {}.", "Минуту - открываю {}."]


class BuddyController(QObject):
    hotkey_setting_changed = Signal(bool)

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.audio = AudioManager(float(cfg.get("volume")), bool(cfg.get("sfx_enabled")),
                                  bool(cfg.get("voice_enabled")))
        self.wm = WindowManager()
        self.ai = AIClient(cfg.api_key, cfg.get("base_url"), cfg.get("model"),
                           cfg.get("system_prompt"), float(cfg.get("temperature")),
                           int(cfg.get("history_length")))
        self.mascot = MascotWindow(cfg, self.audio)
        self.bubble = ChatBubble(bool(cfg.get("voice_enabled")), int(cfg.get("typing_speed_ms")))
        self.worker: AIWorker | None = None
        self.pending_hwnd: int | None = None
        self.pending_commands: list[Command] = []
        self._greeted = False
        self._bubble_was_open = False
        self._settings: SettingsDialog | None = None

        self.mascot.clicked.connect(self.on_mascot_clicked)
        self.mascot.menu_requested.connect(self.show_menu)
        self.mascot.moved.connect(self._follow)
        self.bubble.submitted.connect(self.on_submit)
        self.bubble.voice_toggled.connect(self.set_voice)
        self.bubble.clear_requested.connect(self.clear_dialog)
        self.bubble.closed.connect(lambda: self.mascot.set_hold_still(False))
        self.bubble.typing_tick.connect(self.audio.speech_tick)
        self.bubble.typing_finished.connect(self.on_typing_finished)

        self.fg_timer = QTimer(self)
        self.fg_timer.timeout.connect(self.wm.track_foreground)
        self.fg_timer.start(400)

        self.launcher = AppLauncher()
        self.launcher.refresh_async()

    def start(self) -> None:
        geo = QGuiApplication.primaryScreen().availableGeometry()
        x = geo.x() + geo.width() - 220
        y = geo.y() + geo.height() * (0.35 if self.cfg.get("physics_mode") != "free" else 1.0)
        self.mascot.place_at(x, y)
        self.mascot.show()
        QTimer.singleShot(1400, lambda: self.mascot.react("wave"))

    def is_visible(self) -> bool:
        return self.mascot.isVisible()

    def toggle_visible(self) -> None:
        if self.mascot.isVisible():
            self._bubble_was_open = self.bubble.isVisible()
            self.bubble.hide()
            self.mascot.hide()
        else:
            self.mascot.show()
            self.mascot.spawn("sparkle", 4)
            self.mascot.react("jump", sound=True)
            if self._bubble_was_open:
                self.bubble.open_at(self.mascot.head_anchor(), focus=False)

    def on_hotkey(self) -> None:
        if not self.cfg.get("hotkey_enabled"):
            return
        focus = QGuiApplication.focusObject()
        if isinstance(focus, (QLineEdit, QPlainTextEdit)) and QGuiApplication.focusWindow():
            return
        self.toggle_visible()

    def _follow(self) -> None:
        if self.bubble.isVisible():
            self.bubble.reposition(self.mascot.head_anchor())

    def on_mascot_clicked(self) -> None:
        if self.mascot.state == "sleep":
            self.mascot.touch()
            self.mascot.react("surprised")
        else:
            self.mascot.react()
        self.audio.play_voice_reaction()
        if not self.bubble.isVisible():
            self.open_chat()

    def open_chat(self) -> None:
        self.mascot.set_hold_still(True)
        self.bubble.open_at(self.mascot.head_anchor())
        if not self._greeted:
            self._greeted = True
            hint = "" if self.cfg.api_key else " (Сначала укажите API-ключ в 'Настройках'.)"
            greeting = ("Привет! Я Зета - ваш деловой ассистент. Спросите что-нибудь "
                        "или попросите навести порядок с окнами." + hint)
            self.bubble.type_text(greeting)
            self.mascot.set_busy("talk")
            self.audio.start_speech(len(greeting))

    def show_menu(self, pos: QPoint) -> None:
        menu = QMenu()
        menu.setStyleSheet(MENU_STYLE)
        menu.addAction("Поговорить", self.open_chat)
        menu.addAction("Открыть приложение...", self.prompt_open)
        menu.addAction("Настройки", self.open_settings)
        voice = QAction("Озвучка", menu, checkable=True)
        voice.setChecked(bool(self.cfg.get("voice_enabled")))
        voice.toggled.connect(self.set_voice)
        menu.addAction(voice)
        walk = QAction("Гулять", menu, checkable=True)
        walk.setChecked(bool(self.cfg.get("walk_enabled")))
        walk.toggled.connect(lambda on: self._set_and_save("walk_enabled", on))
        menu.addAction(walk)

        win = menu.addMenu("Активное окно")
        win.setStyleSheet(MENU_STYLE)
        hwnd = self.wm.target()
        title = self.wm.title(hwnd) if hwnd else ""
        head = win.addAction(f"'{title[:40]}'" if title else "Окно не выбрано")
        head.setEnabled(False)
        win.addSeparator()
        for label, action in (("Свернуть", "minimize"), ("Развернуть", "maximize"),
                              ("Восстановить", "restore"), ("По центру", "center"),
                              ("Левая половина", "snap_left"), ("Правая половина", "snap_right"),
                              ("Толкнуть ←", "push_left"), ("Толкнуть →", "push_right")):
            act = win.addAction(label, lambda a=action: self.window_action(a))
            act.setEnabled(bool(hwnd) and self.wm.available)

        emo = menu.addMenu("Эмоция")
        emo.setStyleSheet(MENU_STYLE)
        for label, name in (("Помахать", "wave"), ("Прыжок", "jump"),
                            ("Сердечко", "heart"), ("Смутиться", "shy")):
            emo.addAction(label, lambda n=name: self.mascot.react(n))

        menu.addSeparator()
        menu.addAction("Скрыть   ( \\ )", self.toggle_visible)
        menu.addAction("Выход", self.quit)
        menu.exec(pos)

    def _set_and_save(self, key: str, value) -> None:
        self.cfg.set(key, value)
        self.cfg.save()

    def set_voice(self, on: bool) -> None:
        self._set_and_save("voice_enabled", bool(on))
        self.audio.voice_enabled = bool(on)
        if not on:
            self.audio.stop_speech(immediate=True)
        self.bubble.voice_cb.blockSignals(True)
        self.bubble.voice_cb.setChecked(bool(on))
        self.bubble.voice_cb.blockSignals(False)

    def open_settings(self) -> None:
        if self._settings and self._settings.isVisible():
            self._settings.activateWindow()
            return
        self._settings = SettingsDialog(self.cfg)
        if self._settings.exec() == QDialog.DialogCode.Accepted:
            self._settings.apply()
            self.apply_settings()
        self._settings = None

    def apply_settings(self) -> None:
        c = self.cfg
        self.ai.configure(api_key=c.api_key, base_url=c.get("base_url"), model=c.get("model"),
                          system_prompt=c.get("system_prompt"),
                          temperature=float(c.get("temperature")),
                          history_length=int(c.get("history_length")))
        self.audio.sfx_enabled = bool(c.get("sfx_enabled"))
        self.audio.set_volume(float(c.get("volume")))
        self.set_voice(bool(c.get("voice_enabled")))
        self.bubble.typing_speed_ms = int(c.get("typing_speed_ms"))
        self.mascot.set_scale(int(c.get("scale")))
        self.hotkey_setting_changed.emit(bool(c.get("hotkey_enabled")))
        self._follow()

    def clear_dialog(self) -> None:
        self.ai.clear_history()
        self.bubble.type_text("Начнём с чистого листа. Чем займёмся?")

    def say(self, text: str) -> None:
        self._greeted = True
        self.mascot.set_hold_still(True)
        if not self.bubble.isVisible():
            self.bubble.open_at(self.mascot.head_anchor(), focus=False)
        self.mascot.set_busy("talk")
        self.audio.start_speech(len(text))
        self.bubble.type_text(text)

    def prompt_open(self) -> None:
        self.open_chat()
        self.bubble.input.setText("открой ")
        self.bubble.input.setFocus()

    def open_targets(self, targets: list[str], allow_raw: bool = True,
                     quiet_fail: bool = False, silent_success: bool = False) -> bool:
        if not targets:
            self.say("Что открыть? Например: 'открой телеграм', 'запусти стим', 'открой загрузки'.")
            return True
        opened, web, store, missing, errors = [], [], [], [], []
        for query in targets[:6]:
            match = self.launcher.resolve(query, allow_raw=allow_raw)
            if match is None:
                missing.append(query)
                continue
            ok, info = self.launcher.launch(match)
            if not ok:
                errors.append(info)
            elif match.web_fallback and match.spec[1].startswith("steam://"):
                store.append(match.title)
            elif match.web_fallback:
                web.append(match.title)
            else:
                opened.append(match.title)
        if quiet_fail and not (opened or web or store or errors):
            return False

        parts = []
        if opened:
            parts.append(random.choice(OPEN_PHRASES).format(", ".join(opened)))
        if web:
            parts.append(f"{', '.join(web)} на компьютере не нашла - открываю веб-версию.")
        if store:
            parts.append(f"{', '.join(store)} не установлена - открываю в Steam.")
        parts += errors
        for query in missing:
            hints = self.launcher.suggest(query)
            parts.append(f"Не нашла '{query}'." + (f" Может, {' / '.join(hints)}?" if hints else ""))
        if missing and self.launcher.refreshing:
            parts.append("(Ещё сканирую установленные программы - попробуйте через пару секунд.)")

        if opened or web or store:
            self.mascot.react("jump")
            self.mascot.spawn("sparkle", 3)
        else:
            self.mascot.react("shy", sound=False)
        if not (silent_success and not missing and not errors):
            self.say(" ".join(parts))
        return True

    def on_submit(self, text: str) -> None:
        self.mascot.touch()
        if text.startswith("/"):
            self.local_command(text[1:].strip())
            return
        targets = parse_open_command(text)
        if targets is not None:
            long_request = sum(len(t.split()) for t in targets) > 4
            if self.open_targets(targets, quiet_fail=long_request):
                return
        if self.worker is not None:
            return
        hwnd = self.wm.target()
        self.pending_hwnd = hwnd
        self.bubble.set_thinking()
        self.mascot.set_busy("think")
        self.worker = AIWorker(self.ai, text, self._context(hwnd))
        self.worker.done.connect(self.on_ai_done)
        self.worker.failed.connect(self.on_ai_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _worker_finished(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = None

    def _context(self, hwnd: int | None) -> str:
        s = QGuiApplication.primaryScreen()
        g, d = s.geometry(), s.devicePixelRatio()
        lines = [f"Основной экран: {int(g.width() * d)}x{int(g.height() * d)} пикселей."]
        if self.wm.available and hwnd:
            lines.append(f"Активное окно пользователя: {self.wm.describe(hwnd)}.")
        else:
            lines.append("Активное окно не определено - команды [[window:...]] сейчас не сработают.")
        return "\n".join(lines)

    def on_ai_done(self, reply: AIReply) -> None:
        self.pending_commands = reply.commands
        text = reply.text or ("Готово." if reply.commands else "...")
        self.mascot.set_busy("talk")
        self.audio.start_speech(len(text))
        self.bubble.type_text(text)

    def on_ai_failed(self, message: str) -> None:
        self.mascot.set_busy(None)
        self.bubble.show_error(message)
        self.mascot.react("shy", sound=False)
        self.mascot.spawn("question")

    def on_typing_finished(self) -> None:
        self.audio.stop_speech()
        self.mascot.set_busy(None)
        commands, self.pending_commands = self.pending_commands, []
        if commands:
            self.execute(commands, self.pending_hwnd)

    def local_command(self, cmd: str) -> None:
        parts = cmd.lower().split()
        if not parts or parts[0] in ("help", "?", "помощь"):
            self.bubble.type_text(HELP_TEXT)
            return
        if parts[0] == "clear":
            self.clear_dialog()
            return
        if parts[0] in ("apps", "приложения"):
            if len(parts) > 1 and parts[1] in ("refresh", "update", "обновить"):
                started = self.launcher.refresh_async(force=True)
                self.say("Пересканирую установленные программы - это займёт несколько секунд."
                         if started else "Уже сканирую, секунду.")
            else:
                s = self.launcher.stats()
                when = (time.strftime("%d.%m %H:%M", time.localtime(s["updated_at"]))
                        if s["updated_at"] else "ещё строится")
                self.say(f"В словаре {s['catalog']} записей и {s['aliases']} названий. "
                         f"Установленных программ найдено: {s['installed']} (индекс от {when}).")
            return
        if parts[0] in ("open", "открой", "run", "запусти"):
            self.open_targets(parse_open_command("открой " + " ".join(cmd.split()[1:])) or [])
            return
        if parts[0] in ("find", "найди"):
            query = " ".join(cmd.split()[1:])
            found = self.launcher.candidates(query, 6)
            lines = [f"{m.title} - {m.score:.2f}" for m in found] or ["ничего не нашлось"]
            self.say(f"Кандидаты для '{query}':\n\n" + "\n\n".join(lines))
            return
        key = " ".join(parts[:2]) if " ".join(parts[:2]) in LOCAL_COMMANDS else parts[0]
        if key not in LOCAL_COMMANDS:
            self.bubble.show_error(f"Неизвестная команда /{cmd}. Наберите /help")
            return
        kind, action = LOCAL_COMMANDS[key]
        args = [int(a) for a in parts[1:] if a.lstrip("-").isdigit()]
        self.execute([Command(kind, action, args)], self.wm.target())

    def window_action(self, action: str) -> None:
        self.execute([Command("window", action)], self.wm.target())

    def execute(self, commands: list[Command], hwnd: int | None) -> None:
        tasks: list[Task] = []
        opens = [c.value for c in commands if c.kind == "open" and c.value]
        if opens:
            self.open_targets(opens, allow_raw=False, silent_success=True)
        for c in commands:
            if c.kind == "emote" and c.action in sprites.REACTIONS:
                tasks.append(ReactTask(c.action))
            elif c.kind == "window":
                tasks.extend(self._window_tasks(c, hwnd))
        self.mascot.run_tasks(tasks)

    def _window_tasks(self, c: Command, hwnd: int | None) -> list[Task]:
        wm = self.wm
        if not wm.available:
            self.bubble.show_error("Управление окнами доступно только в Windows.")
            return []
        if not hwnd or not wm.is_window(hwnd):
            self.bubble.show_error("Не вижу активного окна - кликните по нужному окну и повторите.")
            return []
        a, args = c.action, c.args
        if a == "minimize":
            return [PoseTask("push", 420, on_end=lambda: wm.minimize(hwnd), fx="sparkle")]
        if a == "maximize":
            return [PoseTask("push", 380, on_end=lambda: wm.maximize(hwnd), fx="sparkle")]
        if a == "restore":
            return [PoseTask("push", 320, on_end=lambda: wm.restore(hwnd), fx="sparkle")]
        if a == "center":
            return [WindowAnimTask(wm, hwnd, lambda rc, wa: Rect(
                wa.x + (wa.w - rc.w) // 2, wa.y + (wa.h - rc.h) // 2, rc.w, rc.h))]
        if a in ("snap_left", "snap_right"):
            left = a == "snap_left"
            return [WindowAnimTask(wm, hwnd, lambda rc, wa: Rect(
                wa.x if left else wa.x + wa.w // 2, wa.y, wa.w // 2, wa.h))]
        if a == "move" and len(args) >= 2:
            def move_target(rc, wa, x=args[0], y=args[1]):
                nx, ny = wm.clamp_position(hwnd, x, y)
                return Rect(nx, ny, rc.w, rc.h)
            return [WindowAnimTask(wm, hwnd, move_target, 520)]
        if a == "resize" and len(args) >= 2:
            return [WindowAnimTask(wm, hwnd, lambda rc, wa, w=args[0], h=args[1]: Rect(
                rc.x, rc.y, max(200, min(w, wa.w)), max(120, min(h, wa.h))), 480)]
        if a in ("push_left", "push_right"):
            d = -1 if a == "push_left" else 1
            return [HopTask(lambda m: self._push_spot(m, hwnd, d)), PushWindowTask(wm, hwnd, d)]
        return []

    def _push_spot(self, m: MascotWindow, hwnd: int, d: int):
        wm = self.wm
        if wm.is_minimized(hwnd) or wm.is_maximized(hwnd):
            wm.restore(hwnd)
        rc = wm.rect(hwnd)
        if not rc:
            return None
        lx1, _ = phys_to_logical(rc.x, rc.y)
        lx2, ly2 = phys_to_logical(rc.right, rc.bottom)
        edge = lx1 if d > 0 else lx2
        x = edge - d * m.sw * 0.3
        geo = screen_at(x, ly2 - 10).availableGeometry()
        y = min(ly2, geo.y() + geo.height())
        y = max(y, geo.y() + m.sh + 10)
        x = max(geo.x() + m.sw * 0.4, min(geo.x() + geo.width() - m.sw * 0.4, x))
        return x, y

    def quit(self) -> None:
        self.bubble.hide()
        self.mascot.hide()
        if self.worker is not None:
            self.worker.wait(1500)
        self.audio.shutdown()
        self.cfg.save()
        QGuiApplication.quit()
