from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from config import BASE_DIR

CATALOG_DIR = BASE_DIR / "catalog"
CACHE_PATH = BASE_DIR / "apps_cache.json"
IS_WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000
CACHE_MAX_AGE = 12 * 3600
TARGET_TYPES = {"name", "exe", "path", "uwp", "uri", "url", "cmd", "shell",
                "steam", "epic", "group", "special"}


_RU_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ә": "a", "ғ": "g", "қ": "k", "ң": "n", "ө": "o", "ұ": "u", "ү": "u", "һ": "h", "і": "i",
}
_EN_KEYS = "`qwertyuiop[]asdfghjkl;'zxcvbnm,."
_RU_KEYS = "ёйцукенгшщзхъфывапролджэячсмитьбю"
_EN2RU = str.maketrans(_EN_KEYS, _RU_KEYS)
_RU2EN = str.maketrans(_RU_KEYS, _EN_KEYS)
_NON_WORD = re.compile(r"[^0-9a-zа-яәғқңөұүһі+#]+")
_CYR = re.compile(r"[а-яәғқңөұүһі]")
_LAT = re.compile(r"[a-z]")

_RU_ENDINGS = sorted([
    "ами", "ями", "ого", "его", "ому", "ему", "ыми", "ими", "ой", "ей", "ом", "ем", "ую",
    "юю", "ая", "яя", "ое", "ее", "ые", "ие", "ых", "их", "ах", "ях", "ам", "ям", "ов",
    "ев", "у", "ю", "а", "я", "е", "ы", "и", "о", "й", "ь",
], key=len, reverse=True)


def norm(text: str) -> str:
    text = text.lower().replace("ё", "е")
    return " ".join(_NON_WORD.sub(" ", text).split())


def swap_layout(text: str) -> str:
    low = text.lower()
    lat, cyr = len(_LAT.findall(low)), len(_CYR.findall(low))
    return low.translate(_EN2RU) if lat > cyr else low.translate(_RU2EN)


def stem_word(word: str) -> str:
    if len(word) < 4 or not _CYR.search(word):
        return word
    for end in _RU_ENDINGS:
        if word.endswith(end) and len(word) - len(end) >= 3:
            return word[: -len(end)]
    return word


def stem_key(text: str) -> str:
    return " ".join(stem_word(w) for w in norm(text).split())


def lat_key(text: str) -> str:
    s = "".join(_RU_LAT.get(ch, ch) for ch in norm(text))
    for a, b in (("wh", "v"), ("ph", "f"), ("ck", "k"), ("qu", "kv"), ("kh", "h"),
                 ("chr", "kr"), ("sch", "sh"), ("tch", "ch"), ("x", "ks"), ("w", "v"),
                 ("q", "k"), ("j", "dzh"), ("y", "i"), ("ee", "i"), ("oo", "u")):
        s = s.replace(a, b)
    s = re.sub(r"c(?=[eiy])", "s", s)
    s = re.sub(r"c(?!h)", "k", s)
    s = re.sub(r"(?<=\w{3})e\b", "", s)
    s = re.sub(r"(.)\1+", r"\1", s)
    return s.replace(" ", "")


@dataclass
class Entry:
    id: str
    name: str
    targets: list[tuple[str, str]]
    aliases: list[str]


@dataclass
class Installed:
    name: str
    kind: str
    value: str
    exe: str = ""
    source: str = ""


@dataclass
class Match:
    title: str
    score: float
    entry: Entry | None = None
    installed: Installed | None = None
    key: str = ""
    spec: tuple[str, str] | None = None
    web_fallback: bool = False


def load_catalog(folder: Path = CATALOG_DIR) -> tuple[dict[str, Entry], list[str]]:
    entries: dict[str, Entry] = {}
    problems: list[str] = []
    if not folder.is_dir():
        return entries, [f"нет папки {folder}"]
    for path in sorted(folder.glob("*.txt")):
        for n, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(" | ")]
            if len(parts) != 4:
                problems.append(f"{path.name}:{n}: ожидалось 4 поля")
                continue
            eid, name, targets_raw, aliases_raw = parts
            targets = []
            for t in targets_raw.split(";"):
                t = t.strip()
                if not t:
                    continue
                kind, _, value = t.partition(":")
                kind = kind.strip().lower()
                if kind not in TARGET_TYPES or not value.strip():
                    problems.append(f"{path.name}:{n}: неизвестная цель '{t}'")
                    continue
                targets.append((kind, value.strip()))
            aliases = [a.strip() for a in aliases_raw.split(",") if a.strip()]
            if eid in entries:
                problems.append(f"{path.name}:{n}: повтор id {eid}")
                continue
            entries[eid] = Entry(eid, name, targets, [name] + aliases)
    return entries, problems


_JUNK_NAME = re.compile(
    r"uninstall|удал|readme|read me|help|справк|documentation|документац|website|"
    r"веб-сайт|license|лиценз|changelog|release notes|what'?s new|support|поддержк|"
    r"manual|руководств|faq|сайт", re.I)


def _run_powershell(script: str, timeout: int = 45) -> str:
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script],
            capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
        return out.stdout.decode("utf-8", "replace")
    except Exception as exc:
        print(f"[launcher] powershell: {exc}")
        return ""


def lnk_target(path: Path) -> str:
    try:
        data = path.read_bytes()[:65536]
        if len(data) < 0x4C or data[:4] != b"\x4c\x00\x00\x00":
            return ""
        flags = int.from_bytes(data[0x14:0x18], "little")
        pos = 0x4C
        if flags & 0x1:
            pos += 2 + int.from_bytes(data[pos:pos + 2], "little")
        if not flags & 0x2:
            return ""
        li = pos
        header = int.from_bytes(data[li + 4:li + 8], "little")
        if not int.from_bytes(data[li + 8:li + 12], "little") & 0x1:
            return ""
        if header >= 0x24:
            off_u = int.from_bytes(data[li + 28:li + 32], "little")
            if off_u:
                raw = data[li + off_u:]
                end = next((i for i in range(0, len(raw) - 1, 2) if raw[i:i + 2] == b"\x00\x00"), len(raw))
                return raw[:end].decode("utf-16le", "replace")
        off = int.from_bytes(data[li + 16:li + 20], "little")
        end = data.index(b"\x00", li + off)
        return data[li + off:end].decode("mbcs" if IS_WINDOWS else "latin-1", "replace")
    except Exception:
        return ""


def _desktop_dirs() -> list[Path]:
    dirs = [Path(os.environ.get("USERPROFILE", "")) / "Desktop",
            Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"]
    if IS_WINDOWS:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
                dirs.append(Path(winreg.QueryValueEx(k, "Desktop")[0]))
        except OSError:
            pass
    return dirs


def discover_installed() -> list[Installed]:
    if not IS_WINDOWS:
        return []
    found: list[Installed] = []

    raw = _run_powershell("Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress")
    try:
        data = json.loads(raw) if raw.strip() else []
        for item in [data] if isinstance(data, dict) else data:
            name, appid = item.get("Name") or "", item.get("AppID") or ""
            if name and appid and not _JUNK_NAME.search(name):
                exe = appid.replace("/", "\\").rsplit("\\", 1)[-1] if appid.lower().endswith(".exe") else ""
                found.append(Installed(name, "appsfolder", appid, exe, "start"))
    except (json.JSONDecodeError, AttributeError) as exc:
        print(f"[launcher] Get-StartApps: {exc}")

    roots = [Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
             Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
             *_desktop_dirs()]
    for root in roots:
        if not root.is_dir():
            continue
        for path in list(root.rglob("*.lnk")) + list(root.glob("*.url")):
            if _JUNK_NAME.search(path.stem):
                continue
            target = lnk_target(path) if path.suffix.lower() == ".lnk" else ""
            exe = target.rsplit("\\", 1)[-1] if target.lower().endswith(".exe") else ""
            found.append(Installed(path.stem, "file", str(path), exe, "shortcut"))

    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for sub in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
                        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths"):
                try:
                    key = winreg.OpenKey(hive, sub)
                except OSError:
                    continue
                with key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        exe = winreg.EnumKey(key, i)
                        try:
                            with winreg.OpenKey(key, exe) as k:
                                target = os.path.expandvars(str(winreg.QueryValueEx(k, "")[0]).strip('"'))
                        except OSError:
                            continue
                        if exe.lower().endswith(".exe") and os.path.exists(target):
                            found.append(Installed(Path(exe).stem, "file", target, exe, "apppaths"))
    except ImportError:
        pass

    found += _steam_games() + _epic_games()
    return found


def _steam_games() -> list[Installed]:
    games: list[Installed] = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            steam = Path(winreg.QueryValueEx(k, "SteamPath")[0])
    except (ImportError, OSError):
        return games
    libs = {steam}
    vdf = steam / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="replace")):
            libs.add(Path(p.replace("\\\\", "\\")))
    for lib in libs:
        for acf in (lib / "steamapps").glob("appmanifest_*.acf"):
            text = acf.read_text(encoding="utf-8", errors="replace")
            appid = re.search(r'"appid"\s+"(\d+)"', text)
            name = re.search(r'"name"\s+"([^"]+)"', text)
            if appid and name and not re.search(r"redistributable|steamworks common|proton|runtime", name.group(1), re.I):
                games.append(Installed(name.group(1), "steam", appid.group(1), "", "steam"))
    return games


def _epic_games() -> list[Installed]:
    games: list[Installed] = []
    folder = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Epic\EpicGamesLauncher\Data\Manifests"
    for item in folder.glob("*.item") if folder.is_dir() else []:
        try:
            d = json.loads(item.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        name, app = d.get("DisplayName"), d.get("AppName")
        if not name or not app:
            continue
        ns, cid = d.get("CatalogNamespace"), d.get("CatalogItemId")
        ref = f"{ns}%3A{cid}%3A{app}" if ns and cid else app
        games.append(Installed(name, "epic", ref, app, "epic"))
    return games


def scheme_registered(uri: str) -> bool:
    scheme = uri.split(":", 1)[0].lower()
    if scheme in ("http", "https", "shell", "file", "mailto") or scheme.startswith("ms-"):
        return True
    if not IS_WINDOWS:
        return False
    try:
        import winreg
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, scheme).Close()
        return True
    except OSError:
        return False


def _find_command(cmd: str) -> bool:
    exe = os.path.expandvars(cmd.split(" ", 1)[0])
    if os.path.isabs(exe):
        return os.path.exists(exe)
    dirs = [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), d) for d in ("System32", "")]
    dirs += os.environ.get("PATH", "").split(os.pathsep)
    names = [exe] if Path(exe).suffix else [exe + e.lower() for e in os.environ.get("PATHEXT", ".EXE").split(";")]
    return any(os.path.exists(os.path.join(d, n)) for d in dirs if d for n in names)


def _expand_path(pattern: str) -> str | None:
    expanded = os.path.expandvars(pattern)
    if "*" in expanded:
        import glob
        hits = sorted(glob.glob(expanded), reverse=True)
        return hits[0] if hits else None
    return expanded if os.path.exists(expanded) else None


def default_browser() -> str | None:
    if not IS_WINDOWS:
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice") as k:
            prog = winreg.QueryValueEx(k, "ProgId")[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{prog}\shell\open\command") as k:
            cmd = winreg.QueryValueEx(k, "")[0]
        m = re.match(r'"([^"]+)"|(\S+)', cmd)
        path = (m.group(1) or m.group(2)) if m else ""
        return path if path and os.path.exists(path) else None
    except OSError:
        return None


VERBS = {
    "открой", "откройте", "открыть", "открывай", "открывайте", "откроешь", "откроете", "открою",
    "отрой", "откой", "открои", "откр", "открый", "аткрой", "откройка",
    "запусти", "запустите", "запустить", "запускай", "запускайте", "запустишь", "запуск",
    "запусть", "зупусти", "запусли",
    "включи", "включите", "включить", "включай", "включайте", "включишь", "вкл", "вкючи",
    "вруби", "врубай", "врубить", "врубите", "стартани", "стартуй", "стартани", "старт",
    "активируй", "покажи", "показать", "отобрази", "зайди", "зайти", "перейди", "перейти",
    "иди", "загрузи", "подними", "разверни", "вызови", "дай", "давай",
    "open", "launch", "run", "start", "execute", "exec", "opn", "lauch", "lunch", "strat", "goto",
    "аш", "аша", "ашшы", "ашып", "ашыңыз", "ашыныз", "қос", "қосшы", "қосыңыз", "кос", "косшы",
}
VERB_PAIRS = {("go", "to"), ("іске", "қос"), ("иске", "кос"), ("іске", "қосшы")}
FILLERS = {
    "зета", "зет", "zeta", "zetabuddy", "эй", "hey", "ok", "окей", "ок", "ну", "а", "ка", "ко",
    "пожалуйста", "пожалуста", "пожалуйсто", "плиз", "плз", "пж", "пжл", "пжлст", "please", "pls", "plz",
    "мне", "нам", "быстро", "быстрее", "срочно", "скорее", "сейчас", "щас", "давай", "давайка",
    "можешь", "можете", "мог", "могла", "могли", "бы", "ли", "ты", "вы", "сможешь", "будь",
    "добра", "добр", "любезна", "хочу", "хотел", "хотела", "надо", "нужно", "пора", "чтобы", "чтоб",
    "снова", "опять", "заново", "еще", "for", "me", "can", "could", "you", "would", "the", "now",
    "please", "в", "во", "на", "to", "in", "on", "мой", "мою", "моё", "мое", "my", "это", "этот",
    "приложение", "приложения", "программу", "программа", "прогу", "прога", "программку",
    "игру", "игрушку", "сайт", "сайтик", "страницу", "папку", "папка", "app", "application",
    "program", "game", "website", "site", "page", "folder", "қосымша", "қосымшаны", "бағдарлама",
    "бағдарламаны", "ойын", "ойынды", "сайтты", "маған",
}
CONNECTORS = {",", "и", "потом", "затем", "and", "then", "плюс", "және", "также"}
BROWSER_TAIL = {"браузере", "браузер", "browser", "хроме", "chrome"}
RAW_TOKEN = re.compile(r"^(?:https?://\S+|[a-z]:\\\S*|[\w-]+(?:\.[\w-]+)*\.[a-zа-я]{2,}(?:/\S*)?)$", re.I)


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for tok in re.sub(r"([,;])", r" , ", text.lower().replace("ё", "е")).split():
        bare = tok.rstrip("?!.")
        if tok == ",":
            out.append(",")
        elif RAW_TOKEN.match(bare) and not re.fullmatch(r"[\d.]+", bare):
            out.append(bare)
        else:
            out.extend(norm(tok).split())
    return out


def parse_open_command(text: str) -> list[str] | None:
    variants = [text]
    if _LAT.search(text.lower()) and not _CYR.search(text.lower()):
        variants.append(swap_layout(text))
    for variant in variants:
        words = _tokens(variant)
        i = 0
        while i < len(words) and (words[i] in FILLERS or words[i] == ","):
            i += 1
        if i < len(words) and words[i] in VERBS:
            i += 1
        elif i + 1 < len(words) and (words[i], words[i + 1]) in VERB_PAIRS:
            i += 2
        else:
            continue
        chunks, current = [], []
        for w in words[i:]:
            if w in CONNECTORS:
                chunks.append(current)
                current = []
            else:
                current.append(w)
        chunks.append(current)
        parts = []
        for tokens in chunks:
            if len(tokens) > 2 and tokens[-2] in ("в", "во", "in") and tokens[-1] in BROWSER_TAIL:
                tokens = tokens[:-2]
            while tokens and tokens[-1] in FILLERS:
                tokens.pop()
            while tokens and tokens[0] in FILLERS:
                tokens.pop(0)
            if tokens:
                parts.append(" ".join(tokens))
        return parts
    return None


class AppLauncher:
    def __init__(self):
        self.catalog, problems = load_catalog()
        for p in problems[:20]:
            print(f"[launcher] catalog: {p}")
        self.installed: list[Installed] = []
        self.updated_at = 0.0
        self._lock = threading.Lock()
        self._refreshing = False
        self._load_cache()
        self._build_tables()

    def _load_cache(self) -> None:
        try:
            data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            self.installed = [Installed(**d) for d in data.get("apps", [])]
            self.updated_at = float(data.get("updated_at", 0))
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    def refresh_async(self, force: bool = False, on_done=None) -> bool:
        if self._refreshing or (not force and time.time() - self.updated_at < CACHE_MAX_AGE and self.installed):
            return False
        self._refreshing = True

        def work():
            try:
                apps = discover_installed()
                seen, unique = set(), []
                for a in apps:
                    key = (norm(a.name), a.kind, a.value.lower())
                    if key not in seen:
                        seen.add(key)
                        unique.append(a)
                with self._lock:
                    self.installed = unique
                    self.updated_at = time.time()
                    self._build_tables()
                CACHE_PATH.write_text(json.dumps(
                    {"updated_at": self.updated_at, "apps": [a.__dict__ for a in unique]},
                    ensure_ascii=False), encoding="utf-8")
                print(f"[launcher] индекс: {len(unique)} установленных приложений")
            except Exception as exc:
                print(f"[launcher] ошибка индексации: {exc}")
            finally:
                self._refreshing = False
                if on_done:
                    on_done()

        threading.Thread(target=work, daemon=True, name="app-index").start()
        return True

    @property
    def refreshing(self) -> bool:
        return self._refreshing

    def _build_tables(self) -> None:
        by_norm: dict[str, set] = {}
        by_stem: dict[str, set] = {}
        by_lat: dict[str, set] = {}

        def add(text: str, ref):
            n = norm(text)
            if not n:
                return
            by_norm.setdefault(n, set()).add(ref)
            by_stem.setdefault(stem_key(n), set()).add(ref)
            lk = lat_key(n)
            if len(lk) >= 2:
                by_lat.setdefault(lk, set()).add(ref)

        for eid, e in self.catalog.items():
            for alias in e.aliases:
                add(alias, ("c", eid))
        for idx, app in enumerate(self.installed):
            add(app.name, ("i", idx))
            if app.exe:
                add(Path(app.exe).stem, ("i", idx))

        self.by_norm, self.by_stem, self.by_lat = by_norm, by_stem, by_lat
        self.lat_keys = list(by_lat)
        self.exe_map: dict[str, Installed] = {}
        for app in self.installed:
            if app.exe:
                self.exe_map.setdefault(app.exe.lower(), app)
        self.name_list = [(norm(a.name), a, i) for i, a in enumerate(self.installed)]

    def stats(self) -> dict:
        return {
            "catalog": len(self.catalog),
            "aliases": sum(len(e.aliases) for e in self.catalog.values()),
            "installed": len(self.installed),
            "updated_at": self.updated_at,
        }

    def _ref_title(self, ref) -> str:
        return self.catalog[ref[1]].name if ref[0] == "c" else self.installed[ref[1]].name

    def candidates(self, query: str, limit: int = 8) -> list[Match]:
        with self._lock:
            return self._candidates(query, limit)

    def _candidates(self, query: str, limit: int) -> list[Match]:
        scores: dict[tuple, tuple[float, str]] = {}

        def put(ref, score, key):
            if ref[0] == "i":
                src = self.installed[ref[1]].source
                score *= {"start": 0.98, "shortcut": 0.97, "steam": 0.98, "epic": 0.98}.get(src, 0.9)
            if score > scores.get(ref, (0, ""))[0]:
                scores[ref] = (score, key)

        variants = [(query, 1.0)]
        swapped = swap_layout(query)
        if norm(swapped) != norm(query):
            variants.append((swapped, 0.97))

        for text, factor in variants:
            n = norm(text)
            if not n:
                continue
            for ref in self.by_norm.get(n, ()):
                put(ref, 1.0 * factor, n)
            for ref in self.by_stem.get(stem_key(n), ()):
                put(ref, 0.96 * factor, n)
            lk = lat_key(n)
            for ref in self.by_lat.get(lk, ()):
                put(ref, 0.93 * factor, n)
            if len(lk) >= 3:
                for key in difflib.get_close_matches(lk, self.lat_keys, n=10, cutoff=0.8):
                    ratio = difflib.SequenceMatcher(None, lk, key).ratio()
                    for ref in self.by_lat[key]:
                        put(ref, ratio * 0.9 * factor, key)
            if len(n) >= 4:
                for name_n, _app, idx in self.name_list:
                    if name_n.startswith(n + " "):
                        put(("i", idx), 0.8 - min(0.1, (len(name_n) - len(n)) / 200), n)

        ranked = sorted(scores.items(), key=lambda kv: -kv[1][0])[:limit * 2]
        out = []
        for ref, (score, key) in ranked:
            if ref[0] == "c":
                out.append(Match(self.catalog[ref[1]].name, score, entry=self.catalog[ref[1]], key=key))
            else:
                app = self.installed[ref[1]]
                out.append(Match(app.name, score, installed=app, key=key))
        return out[:limit]

    def resolve(self, query: str, allow_raw: bool = False, threshold: float = 0.74) -> Match | None:
        found = self._resolve_known(query, threshold)
        if found is None and allow_raw:
            return self._raw_target(query)
        return found

    def _resolve_known(self, query: str, threshold: float) -> Match | None:
        cands = self.candidates(query)
        best_local: Match | None = None
        best_web: Match | None = None
        for m in cands:
            if m.score < threshold:
                break
            if m.installed is not None:
                m.spec = self._installed_spec(m.installed)
            else:
                m.spec = self._entry_spec(m.entry, local_only=True)
                if m.spec is None:
                    fallback = self._entry_spec(m.entry, local_only=False)
                    if fallback and best_web is None:
                        m.spec, m.web_fallback = fallback, True
                        best_web = m
                    continue
            if m.spec and best_local is None:
                best_local = m
                break
        if best_local and best_web:
            return best_local if best_local.score >= best_web.score - 0.12 else best_web
        return best_local or best_web

    def suggest(self, query: str, n: int = 3) -> list[str]:
        titles = []
        for m in self.candidates(query, limit=12):
            if m.score >= 0.45 and m.title not in titles:
                titles.append(m.title)
        return titles[:n]

    @staticmethod
    def _raw_target(query: str) -> Match | None:
        q = query.strip().strip('"')
        if re.match(r"^https?://", q, re.I):
            return Match(q, 1.0, spec=("url", q))
        if re.match(r"^[\w-]+(\.[\w-]+)*\.[a-zа-я]{2,}(/\S*)?$", q, re.I) and " " not in q:
            return Match(q, 1.0, spec=("url", "https://" + q))
        path = os.path.expandvars(q)
        if re.match(r"^[a-z]:\\", path, re.I) and os.path.exists(path):
            return Match(Path(path).name or path, 1.0, spec=("file", path))
        return None

    @staticmethod
    def _installed_spec(app: Installed) -> tuple[str, str]:
        if app.kind == "steam":
            return ("uri", f"steam://rungameid/{app.value}")
        if app.kind == "epic":
            return ("uri", f"com.epicgames.launcher://apps/{app.value}?action=launch&silent=true")
        return (app.kind, app.value)

    def _find_by_name(self, name: str) -> Installed | None:
        n = norm(name)
        exact = [a for nn, a, _ in self.name_list if nn == n]
        if exact:
            return sorted(exact, key=lambda a: {"start": 0, "shortcut": 1}.get(a.source, 2))[0]
        prefix = [a for nn, a, _ in self.name_list if nn.startswith(n + " ")]
        return min(prefix, key=lambda a: len(a.name)) if prefix else None

    def _entry_spec(self, e: Entry, local_only: bool, depth: int = 0) -> tuple[str, str] | None:
        if depth > 3:
            return None
        for kind, value in e.targets:
            spec = None
            if kind == "name":
                app = self._find_by_name(value)
                spec = self._installed_spec(app) if app else None
            elif kind == "exe":
                app = self.exe_map.get(value.lower())
                spec = self._installed_spec(app) if app else None
            elif kind == "path":
                p = _expand_path(value)
                spec = ("file", p) if p else None
            elif kind == "uwp":
                prefix = value.lower()
                app = next((a for a in self.installed
                            if a.kind == "appsfolder" and a.value.lower().startswith(prefix)), None)
                spec = self._installed_spec(app) if app else None
            elif kind == "cmd":
                spec = ("cmd", value) if _find_command(value) else None
            elif kind == "uri":
                spec = ("uri", value) if scheme_registered(value) else None
            elif kind == "shell":
                spec = ("shell", value)
            elif kind == "steam":
                app = next((a for a in self.installed if a.kind == "steam" and a.value == value), None)
                if app:
                    spec = self._installed_spec(app)
                elif not local_only and scheme_registered("steam:"):
                    spec = ("uri", f"steam://rungameid/{value}")
            elif kind == "epic":
                app = next((a for a in self.installed if a.kind == "epic"
                            and value.lower() in (a.exe.lower(), a.value.lower())), None)
                spec = self._installed_spec(app) if app else None
            elif kind == "special" and value == "default_browser":
                exe = default_browser()
                spec = ("file", exe) if exe else None
            elif kind == "group":
                for gid in value.split(","):
                    sub = self.catalog.get(gid.strip())
                    if sub:
                        spec = self._entry_spec(sub, local_only=True, depth=depth + 1)
                        if spec:
                            break
                if spec is None and not local_only:
                    for gid in value.split(","):
                        sub = self.catalog.get(gid.strip())
                        if sub:
                            spec = self._entry_spec(sub, local_only=False, depth=depth + 1)
                            if spec:
                                break
            elif kind == "url" and not local_only:
                spec = ("url", value)
            if spec:
                return spec
        return None

    @staticmethod
    def launch(match: Match) -> tuple[bool, str]:
        if not match.spec:
            return False, f"Не знаю, как запустить '{match.title}'."
        kind, value = match.spec
        try:
            if kind == "appsfolder":
                subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{value}"])
            elif kind == "shell":
                subprocess.Popen(["explorer.exe", value])
            elif kind == "cmd":
                exe, _, args = value.partition(" ")
                exe = os.path.expandvars(exe)
                if args:
                    os.startfile(exe, arguments=os.path.expandvars(args))
                else:
                    os.startfile(exe)
            elif kind in ("file", "url", "uri"):
                os.startfile(value)
            else:
                return False, f"Неизвестный способ запуска: {kind}"
        except OSError as exc:
            return False, f"Не получилось открыть '{match.title}': {exc.strerror or exc}"
        return True, match.title
