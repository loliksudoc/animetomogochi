from __future__ import annotations

import math
import os
import random
import struct
import wave
from pathlib import Path

from config import SOUNDS_DIR

SAMPLE_RATE = 22050
VOICE_DIR = SOUNDS_DIR / "voice"

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

try:
    import pygame
    _HAS_PYGAME = True
except ImportError:
    pygame = None
    _HAS_PYGAME = False

try:
    import winsound
except ImportError:
    winsound = None


def _envelope(i: int, n: int, attack: float = 0.05, curve: float = 4.0) -> float:
    t = i / max(1, n)
    if t < attack:
        return t / attack
    return math.exp(-curve * (t - attack))


def _tone(freq_start: float, freq_end: float, dur: float, vol: float = 0.5,
          shape: str = "sine", curve: float = 4.0, vibrato: float = 0.0) -> list[float]:
    n = int(SAMPLE_RATE * dur)
    out, phase = [], 0.0
    for i in range(n):
        t = i / n
        f = freq_start + (freq_end - freq_start) * t
        if vibrato:
            f *= 1 + 0.04 * math.sin(2 * math.pi * vibrato * i / SAMPLE_RATE)
        phase += 2 * math.pi * f / SAMPLE_RATE
        if shape == "square":
            s = 0.6 if math.sin(phase) >= 0 else -0.6
            s = 0.55 * s + 0.45 * math.sin(phase)
        elif shape == "tri":
            s = 2 / math.pi * math.asin(math.sin(phase))
        else:
            s = math.sin(phase)
        out.append(s * vol * _envelope(i, n, curve=curve))
    return out


def _concat(*parts: list[float], gap: float = 0.0) -> list[float]:
    silence = [0.0] * int(SAMPLE_RATE * gap)
    out: list[float] = []
    for p in parts:
        out.extend(p)
        out.extend(silence)
    return out


def _to_pcm16(samples: list[float]) -> bytes:
    return b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32000)) for s in samples)


def _write_wav(path: Path, samples: list[float]) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(_to_pcm16(samples))


SYNTH = {
    "click.wav": lambda: _tone(700, 1300, 0.07, 0.5, "tri", curve=6),
    "jump.wav": lambda: _tone(320, 820, 0.22, 0.45, "square", curve=3),
    "wave.wav": lambda: _concat(_tone(880, 990, 0.07, 0.4, "tri"), _tone(1180, 1320, 0.09, 0.4, "tri"), gap=0.03),
    "heart.wav": lambda: _concat(_tone(784, 784, 0.1, 0.35), _tone(988, 988, 0.1, 0.35),
                                 _tone(1318, 1318, 0.22, 0.35, curve=3), gap=0.01),
    "shy.wav": lambda: _tone(900, 520, 0.25, 0.35, "sine", curve=3, vibrato=14),
    "bonk.wav": lambda: _tone(260, 140, 0.12, 0.55, "square", curve=5),
    "speech_sound.wav": lambda: _tone(540, 500, 0.045, 0.35, "square", curve=5),
}


def ensure_default_sounds(folder: Path = SOUNDS_DIR) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, make in SYNTH.items():
        path = folder / name
        if not path.exists():
            try:
                _write_wav(path, make())
            except OSError as exc:
                print(f"[audio] Не удалось создать {path}: {exc}")


class AudioManager:
    REACTION_SOUNDS = {
        "jump": "jump.wav", "wave": "wave.wav", "heart": "heart.wav",
        "shy": "shy.wav", "surprised": "bonk.wav", "click": "click.wav",
    }

    def __init__(self, volume: float = 0.6, sfx_enabled: bool = True, voice_enabled: bool = True):
        self.volume = volume
        self.sfx_enabled = sfx_enabled
        self.voice_enabled = voice_enabled
        self._sounds: dict[str, object] = {}
        self._blips: list[object] = []
        self._voice_music: Path | None = None
        self._voice_clips: list[object] = []
        self._react_clips: list[object] = []
        self._voice_channel = None
        self._speech_queue = 0
        self._last_clip = None
        self._ok = False
        ensure_default_sounds()
        self._init_backend()

    def _init_backend(self) -> None:
        if not _HAS_PYGAME:
            print("[audio] pygame не найден - используется winsound (ограниченно).")
            return
        try:
            pygame.mixer.pre_init(SAMPLE_RATE, -16, 1, 512)
            pygame.mixer.init()
            pygame.mixer.set_num_channels(16)
            self._ok = True
        except Exception as exc:
            print(f"[audio] Не удалось инициализировать pygame.mixer: {exc}")
            return

        for name in set(self.REACTION_SOUNDS.values()) | {"speech_sound.wav"}:
            path = SOUNDS_DIR / name
            try:
                self._sounds[name] = pygame.mixer.Sound(str(path))
            except Exception as exc:
                print(f"[audio] Не загружен {path.name}: {exc}")

        custom = self._is_custom("speech_sound.wav")
        if custom and "speech_sound.wav" in self._sounds:
            self._blips = [self._sounds["speech_sound.wav"]]
        else:
            for base in (480, 540, 610, 660):
                pcm = _to_pcm16(_tone(base, base * 0.92, 0.045, 0.35, "square", curve=5))
                try:
                    self._blips.append(pygame.mixer.Sound(buffer=pcm))
                except Exception:
                    pass

        mp3 = SOUNDS_DIR / "voice.mp3"
        if mp3.exists():
            self._voice_music = mp3

        self._load_voice_clips()
        self.set_volume(self.volume)

    def _load_voice_clips(self) -> None:
        if not VOICE_DIR.is_dir():
            return
        for path in sorted(VOICE_DIR.glob("*.wav")):
            try:
                snd = pygame.mixer.Sound(str(path))
            except Exception as exc:
                print(f"[audio] Не загружен {path.name}: {exc}")
                continue
            (self._react_clips if path.stem.startswith("react") else self._voice_clips).append(snd)
        if not self._voice_clips:
            self._voice_clips = list(self._react_clips)
        if not self._react_clips:
            self._react_clips = [s for s in self._voice_clips if s.get_length() <= 1.6]
        if self._voice_clips:
            pygame.mixer.set_reserved(1)
            self._voice_channel = pygame.mixer.Channel(0)
            print(f"[audio] Голос: {len(self._voice_clips)} фраз, {len(self._react_clips)} реплик на клик")

    @staticmethod
    def _is_custom(name: str) -> bool:
        path = SOUNDS_DIR / name
        try:
            expected = len(_to_pcm16(SYNTH[name]())) + 44
            return path.stat().st_size != expected
        except (OSError, KeyError):
            return False

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))
        if not self._ok:
            return
        for snd in list(self._sounds.values()) + self._blips + self._voice_clips + self._react_clips:
            snd.set_volume(self.volume)
        pygame.mixer.music.set_volume(self.volume)

    def play_reaction(self, name: str) -> None:
        if not self.sfx_enabled:
            return
        self._play_file(self.REACTION_SOUNDS.get(name, "click.wav"))

    def play_click(self) -> None:
        self.play_reaction("click")

    def _play_file(self, filename: str) -> None:
        if self._ok and filename in self._sounds:
            self._sounds[filename].play()
        elif winsound is not None:
            path = SOUNDS_DIR / filename
            if path.exists():
                winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)

    @property
    def uses_voice_clips(self) -> bool:
        return self._ok and bool(self._voice_clips)

    @property
    def uses_voice_track(self) -> bool:
        return self._ok and self._voice_music is not None and not self.uses_voice_clips

    def _play_clip(self, pool: list) -> None:
        choices = [c for c in pool if c is not self._last_clip] or pool
        clip = random.choice(choices)
        self._last_clip = clip
        self._voice_channel.play(clip)

    def play_voice_reaction(self) -> None:
        if not (self.voice_enabled and self.uses_voice_clips and self._react_clips):
            return
        if not self._voice_channel.get_busy():
            self._play_clip(self._react_clips)

    def start_speech(self, text_length: int = 0) -> None:
        if not self.voice_enabled:
            return
        if self.uses_voice_clips:
            self._speech_queue = min(3, 1 + text_length // 220)
            self._voice_channel.stop()
            self._play_clip(self._voice_clips)
            self._speech_queue -= 1
            return
        if not self.uses_voice_track:
            return
        try:
            pygame.mixer.music.load(str(self._voice_music))
            pygame.mixer.music.play(loops=-1)
        except Exception as exc:
            print(f"[audio] voice.mp3: {exc}")
            self._voice_music = None

    def speech_tick(self) -> None:
        if not self.voice_enabled or self.uses_voice_track:
            return
        if self.uses_voice_clips:
            if self._speech_queue > 0 and not self._voice_channel.get_busy():
                self._speech_queue -= 1
                self._play_clip(self._voice_clips)
            return
        if self._ok and self._blips:
            random.choice(self._blips).play()
        elif winsound is not None:
            self._play_file("speech_sound.wav")

    def stop_speech(self, immediate: bool = False) -> None:
        self._speech_queue = 0
        if immediate and self._voice_channel is not None:
            self._voice_channel.fadeout(200)
        if self.uses_voice_track:
            try:
                pygame.mixer.music.fadeout(250)
            except Exception:
                pass

    def shutdown(self) -> None:
        if self._ok:
            try:
                pygame.mixer.quit()
            except Exception:
                pass
