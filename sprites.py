from __future__ import annotations

from dataclasses import dataclass, replace

W, H = 32, 43

PALETTE: dict[str, tuple[int, int, int, int]] = {
    "K": (27, 20, 32, 255),
    "R": (224, 49, 43, 255),
    "r": (160, 28, 38, 255),
    "h": (255, 122, 82, 255),
    "Y": (255, 214, 63, 255),
    "y": (232, 154, 0, 255),
    "S": (255, 227, 207, 255),
    "s": (242, 185, 160, 255),
    "B": (43, 100, 232, 255),
    "b": (31, 63, 153, 255),
    "E": (43, 33, 80, 255),
    "I": (91, 73, 184, 255),
    "e": (255, 255, 255, 255),
    "W": (255, 255, 255, 255),
    "w": (214, 219, 232, 255),
    "J": (42, 42, 53, 255),
    "j": (74, 74, 92, 255),
    "k": (17, 17, 22, 255),
    "g": (108, 108, 128, 255),
    "M": (184, 50, 62, 255),
    "P": (255, 143, 168, 255),
    "H": (255, 62, 108, 255),
    "Z": (120, 170, 255, 255),
}


def _m(half: str) -> str:
    assert len(half) == W // 2, (half, len(half))
    return half + half[::-1]


def _ms(halves: list[str]) -> list[str]:
    return [_m(h) for h in halves]


def _flip(rows: list[str]) -> list[str]:
    return [r[::-1] for r in rows]


AHOGE = [
    "................KKKK............",
    "...............KRRhhK...........",
    "..............KRRKKRRK..........",
    "..............KRK..KK...........",
    "..............KRRK..............",
]

HEAD_FRONT = _ms([
    "..........KKKKKK",
    "........KKRRRRRR",
    ".......KRRRRRhhR",
    "......KRRRRRhhRR",
    ".....KRRRRRRRRRR",
    "....KRRRRRRRRRRR",
    "....KRRRRRRRRRRR",
    "...KRRRRRRRRRRRR",
    "...KRRRrRRRRrRRR",
    "...KRRrSrRRRrSrR",
    "..KRRRrSSrRRrSSS",
    "..KRRrSSSSrRrSSS",
    "..KRRrSSSSSSSSSS",
    "..KRrSSSSSSSSSSS",
    "..KRrSSSSSSSSSSS",
    "..KRrSSSSSSSSSSS",
    "..KRRKSSSSSSSSSS",
    "..KRRRKSSSSSSSSS",
    "..KRRRRKKSSSSSSS",
    "..KRRRRRRKKKKKKK",
])

HAIR_BACK_FRONT = _ms([
    "..KRRRRRK.......",
    "..KRRRRRK.......",
    ".KRRRRRK........",
    ".KRRrRRK........",
    ".KRRrRRK........",
    ".KRRrRRK........",
    ".KRRrRRK........",
    ".KRRrRRK........",
    ".KRrRRRK........",
    ".KRrRRK.........",
    ".KRrRRK.........",
    "..KrRRK.........",
    "..KrRK..........",
    "..KRrK..........",
    "...KK...........",
])

GLASSES = _ms([
    "......BBBBBBB...",
    "......B.....B...",
    "......B.....BBBB",
    "......B.....B...",
    "......B.....B...",
    "......BBBBBBB...",
])

STARS = [
    "...........Y....................",
    "..........YYY...................",
    ".......Y...Y............Y.......",
    ".....YYYYY............YYYYY.....",
    "......YyY..............YyY......",
    "......Y.Y..............Y.Y......",
]

EYES = {
    "open": [
        ".......KKKKK........KKKKK.......",
        "........EeEE........EeEE........",
        "........EEEE........EEEE........",
        "........IIII........IIII........",
    ],
    "blink": [
        "................................",
        ".......K................K.......",
        "........KKKK........KKKK........",
        "................................",
    ],
    "happy": [
        "................................",
        ".........KK..........KK.........",
        "........K..K........K..K........",
        "................................",
    ],
    "shy": [
        "........KK............KK........",
        "..........KK........KK..........",
        "........KK............KK........",
        "................................",
    ],
    "surprised": [
        "........KKKK........KKKK........",
        ".......KWWWWK......KWWWWK.......",
        ".......KWEEWK......KWEEWK.......",
        "........KKKK........KKKK........",
    ],
    "side": [
        ".......KKKKK........KKKKK.......",
        "........wwEe........wwEe........",
        "........wwEE........wwEE........",
        "........wwII........wwII........",
    ],
}

MOUTHS = {
    "smile": [
        "..............M..M..............",
        "...............MM...............",
    ],
    "neutral": [
        "................................",
        "...............MM...............",
    ],
    "open": [
        "..............MMMM..............",
        "...............PP...............",
    ],
    "o": [
        "...............MM...............",
        "...............MM...............",
    ],
    "wavy": [
        "................................",
        "..............M.MM..............",
    ],
}

BLUSH = [
    ".......PPP............PPP.......",
]

BODY_FRONT = _ms([
    ".........KJJWWWW",
    "........KJJJjWWW",
    "........KJJJJjWW",
    "........KJJJJJjW",
    "........KJJJJJJj",
    "........KJJJJJJJ",
    "........KJJJJJJJ",
    "........KJJJJJJJ",
    "........KKKKKKKK",
    ".........KJJJJjJ",
    ".........KJJJJjJ",
    ".........KJJJJjJ",
    ".........KKKKKKK",
])

TIE = [
    "...............bb...............",
    "...............bb...............",
    "..............bbbb..............",
    "...............bb...............",
    "................................",
    "...............gg...............",
]

ARMS = {
    "down": _ms([
        "................",
        "......KKK.......",
        ".....KjJK.......",
        ".....KjJK.......",
        ".....KjJK.......",
        ".....KjJK.......",
        ".....KWWK.......",
        ".....KSSK.......",
        "......KK........",
    ]),
    "together": [
        "................................",
        "......KKK..............KKK......",
        ".....KjJK..............KJjK.....",
        ".....KjJK..............KJjK.....",
        ".....KjJKKKKK......KKKKKJjK.....",
        "......KjJJJJWWSSSSWWJJJJjK......",
        ".......KKKKKKKKKKKKKKKKKK.......",
    ],
    "out": _ms([
        "..KKKKKKK.......",
        ".KSSWJjJJ.......",
        ".KSSWJJJJ.......",
        "..KKKKKKK.......",
    ]),
    "out_up": _ms([
        ".KKKKKKKK.......",
        "KSSWJjJJJ.......",
        "KSSWJJJJ........",
        ".KKKKKKK........",
    ]),
}

WAVE_ARM = {
    0: [
        "............................KKK.",
        "...........................KSSSK",
        "...........................KSSSK",
        "...........................KWWK.",
        "..........................KJjK..",
        ".........................KJjK...",
        "........................KJjK....",
        ".......................KJJK.....",
        ".......................KJK......",
    ],
    1: [
        "...........................KKK..",
        "..........................KSSSK.",
        "..........................KSSSK.",
        "...........................KWWK.",
        "..........................KJjK..",
        ".........................KJjK...",
        "........................KJjK....",
        ".......................KJJK.....",
        ".......................KJK......",
    ],
}

LEGS = {
    "stand": _ms([
        "..........KSSK..",
        "..........KSSK..",
        "..........KSSK..",
        "..........KSSK..",
        "..........KkkK..",
        ".........KkgkkK.",
        ".........KKKKKK.",
    ]),
    "step": [
        "..........KSSK....KSSK..........",
        "..........KSSK....KSSK..........",
        "..........KkkK....KSSK..........",
        ".........KkgkkK...KSSK..........",
        ".........KKKKKK...KkkK..........",
        ".................KkkgkK.........",
        ".................KKKKKK.........",
    ],
    "dangle": [
        "..........KSSK....KSSK..........",
        "..........KSSK....KSSK..........",
        "..........KSSK....KSSK..........",
        "..........KSSK....KSSK..........",
        "..........KkkK....KSSK..........",
        "..........KkkK....KkkK..........",
        "...........KK.....KkkK..........",
    ],
    "tuck": [
        "..........KSSK....KSSK..........",
        "..........KSSK....KSSK..........",
        "..........KkkK....KkkK..........",
        ".........KkgkkK..KkkgkK.........",
        ".........KKKKKK..KKKKKK.........",
        "................................",
        "................................",
    ],
}
LEGS["step_r"] = _flip(LEGS["step"])
LEGS["dangle_r"] = _flip(LEGS["dangle"])


HEAD_BACK = _ms([
    "..........KKKKKK",
    "........KKRRRRRR",
    ".......KRRRRRRRR",
    "......KRRRRRhhRR",
    ".....KRRRRRhhRRR",
    "....KRRRRRRRRRRR",
    "....KRRRRRRRRRRR",
    "...KRRRRRRRRRRRR",
    "...KRRRRRRRRRRRR",
    "...KRRRRrRRRRRRR",
    "..KRRRRrRRRRRrRR",
    "..KRRRrRRRRRrRRR",
    "..KRRRrRRRRRrRRR",
    "..KRRRrRRRRrRRRR",
    "..KRRRrRRRRrRRRR",
    "..KRRRrRRRRrRRRR",
    "..KRRrRRRRRrRRRR",
    "..KRRrRRRRrRRRRR",
    "..KRRrRRRRrRRRRR",
    "..KRRrRRRRrRRRRR",
])

HAIR_LONG_BACK = _ms([
    "........KRrRRRrR",
    "........KRrRRRrR",
    "........KRrRRrRR",
    "........KRrRRrRR",
    "........KRrRRrRR",
    "........KRrRRrRR",
    "........KrRRrRRR",
    "........KrRRrRRr",
    ".........KRRKrRR",
    ".........KRK.KrK",
    "..........K...K.",
])

BODY_BACK = [row.replace("W", "J").replace("j", "J") for row in BODY_FRONT]


EFFECTS = {
    "heart": [
        ".HH.HH.",
        "HWHHHHH",
        "HHHHHHH",
        ".HHHHH.",
        "..HHH..",
        "...H...",
    ],
    "note": [
        "..KKK",
        "..K.K",
        "..K..",
        "KKK..",
        "KKK..",
    ],
    "sweat": [
        "..Z.",
        ".ZZ.",
        "ZZWZ",
        "ZZZZ",
        ".ZZ.",
    ],
    "z": [
        "KKKK",
        "..K.",
        ".K..",
        "KKKK",
    ],
    "excl": [
        "KK",
        "KK",
        "KK",
        "..",
        "KK",
    ],
    "question": [
        ".KKK.",
        "K...K",
        "...K.",
        "..K..",
        ".....",
        "..K..",
    ],
    "dot": [
        "KK",
        "KK",
    ],
    "sparkle": [
        "..Y..",
        "..Y..",
        "YYWYY",
        "..Y..",
        "..Y..",
    ],
    "star": [
        "..Y..",
        "YYYYY",
        ".YyY.",
        ".Y.Y.",
    ],
}


@dataclass(frozen=True)
class Frame:
    view: str = "front"
    eyes: str = "open"
    mouth: str = "smile"
    arms: str = "down"
    legs: str = "stand"
    blush: bool = False
    body_dy: int = 0
    head_dx: int = 0
    head_dy: int = 0


def _blit(canvas, rows, oy, dx=0, dy=0):
    for r, row in enumerate(rows):
        y = oy + r + dy
        if not 0 <= y < H:
            continue
        for c, ch in enumerate(row):
            if ch == "." or ch == " ":
                continue
            x = c + dx
            if 0 <= x < W:
                canvas[y][x] = ch


def compose(f: Frame) -> list[str]:
    canvas = [["."] * W for _ in range(H)]
    hy = f.body_dy + f.head_dy
    if f.view == "back":
        _blit(canvas, LEGS[f.legs], 36)
        _blit(canvas, BODY_BACK, 23, dy=f.body_dy)
        _blit(canvas, HAIR_LONG_BACK, 24, dx=f.head_dx, dy=f.body_dy)
        _blit_arms(canvas, f, back=True)
        _blit(canvas, HEAD_BACK, 4, dx=f.head_dx, dy=hy)
        _blit(canvas, _flip(STARS), 7, dx=f.head_dx, dy=hy)
        _blit(canvas, _flip(AHOGE), 0, dx=f.head_dx, dy=hy)
        _blit_wave_arm(canvas, f, back=True)
    else:
        _blit(canvas, HAIR_BACK_FRONT, 22, dx=f.head_dx, dy=hy)
        _blit(canvas, LEGS[f.legs], 36)
        _blit(canvas, BODY_FRONT, 23, dy=f.body_dy)
        _blit(canvas, TIE, 23, dy=f.body_dy)
        _blit_arms(canvas, f, back=False)
        _blit(canvas, HEAD_FRONT, 4, dx=f.head_dx, dy=hy)
        _blit(canvas, EYES[f.eyes], 16, dx=f.head_dx, dy=hy)
        _blit(canvas, MOUTHS[f.mouth], 21, dx=f.head_dx, dy=hy)
        if f.blush:
            _blit(canvas, BLUSH, 21, dx=f.head_dx, dy=hy)
        _blit(canvas, GLASSES, 15, dx=f.head_dx, dy=hy)
        _blit(canvas, STARS, 7, dx=f.head_dx, dy=hy)
        _blit(canvas, AHOGE, 0, dx=f.head_dx, dy=hy)
        _blit_wave_arm(canvas, f, back=False)
    return ["".join(row) for row in canvas]


def _blit_wave_arm(canvas, f: Frame, back: bool):
    if f.arms.startswith("wave"):
        arm = WAVE_ARM[int(f.arms[-1])]
        _blit(canvas, _flip(arm) if back else arm, 16, dy=f.body_dy)


def _blit_arms(canvas, f: Frame, back: bool):
    if f.arms.startswith("wave"):
        other = [row[:16] + "." * 16 for row in ARMS["down"]]
        _blit(canvas, _flip(other) if back else other, 23, dy=f.body_dy)
    elif f.arms == "together" and back:
        _blit(canvas, ARMS["down"], 23, dy=f.body_dy)
    else:
        _blit(canvas, ARMS[f.arms], 23, dy=f.body_dy)


def render_rgba(rows: list[str]) -> bytes:
    out = bytearray()
    transparent = (0, 0, 0, 0)
    for row in rows:
        for ch in row:
            out.extend(PALETTE.get(ch, transparent) if ch != "." else transparent)
    return bytes(out)


def effect_rgba(name: str) -> tuple[int, int, bytes]:
    rows = EFFECTS[name]
    w = max(len(r) for r in rows)
    rows = [r.ljust(w, ".") for r in rows]
    return w, len(rows), render_rgba(rows)


F = Frame
_BASE = F()
_WALK = [
    (F(legs="step", body_dy=0), 150),
    (F(legs="stand", body_dy=1), 110),
    (F(legs="step_r", body_dy=0), 150),
    (F(legs="stand", body_dy=1), 110),
]

ANIMATIONS: dict[str, dict] = {
    "idle": {"loop": True, "frames": [
        (_BASE, 2600), (F(eyes="blink"), 130), (_BASE, 1900),
        (F(eyes="blink"), 110), (_BASE, 180), (F(eyes="blink"), 110),
    ]},
    "idle_back": {"loop": True, "frames": [
        (F(view="back"), 900), (F(view="back", head_dx=1), 700),
        (F(view="back"), 900), (F(view="back", head_dx=-1), 700),
    ]},
    "walk_left": {"loop": True, "frames": [(replace(fr, head_dx=-1), d) for fr, d in _WALK]},
    "walk_right": {"loop": True, "frames": [(replace(fr, head_dx=1), d) for fr, d in _WALK]},
    "walk_front": {"loop": True, "frames": _WALK},
    "walk_back": {"loop": True, "frames": [(replace(fr, view="back"), d) for fr, d in _WALK]},
    "drag": {"loop": True, "frames": [
        (F(eyes="shy", mouth="o", arms="out", legs="dangle"), 170),
        (F(eyes="shy", mouth="o", arms="out_up", legs="dangle_r"), 170),
    ]},
    "fall": {"loop": True, "frames": [
        (F(eyes="surprised", mouth="o", arms="out_up", legs="dangle"), 120),
        (F(eyes="surprised", mouth="o", arms="out", legs="dangle_r"), 120),
    ]},
    "land": {"loop": False, "frames": [
        (F(eyes="blink", mouth="neutral", arms="out", body_dy=2), 110),
        (F(eyes="blink", mouth="neutral", body_dy=1), 110),
        (_BASE, 80),
    ]},
    "jump": {"loop": False, "frames": [
        (F(eyes="happy", mouth="smile", body_dy=2), 130),
        (F(eyes="happy", mouth="open", arms="out_up", legs="tuck"), 420),
        (F(eyes="happy", mouth="smile", body_dy=2), 120),
        (F(eyes="happy", mouth="smile"), 300),
    ]},
    "wave": {"loop": False, "frames": [
        (F(eyes="happy", mouth="open", arms="wave0"), 180),
        (F(eyes="happy", mouth="open", arms="wave1"), 180),
    ] * 4 + [(F(eyes="happy", mouth="smile"), 250)]},
    "heart": {"loop": False, "frames": [
        (F(eyes="happy", mouth="smile", arms="together", blush=True), 350),
        (F(eyes="happy", mouth="open", arms="together", blush=True, body_dy=1), 350),
    ] * 3},
    "shy": {"loop": False, "frames": [
        (F(eyes="shy", mouth="wavy", arms="together", blush=True, head_dx=-1), 260),
        (F(eyes="shy", mouth="wavy", arms="together", blush=True, head_dx=1), 260),
    ] * 3 + [(F(eyes="open", mouth="wavy", arms="together", blush=True), 400)]},
    "surprised": {"loop": False, "frames": [
        (F(eyes="surprised", mouth="o", arms="out_up", body_dy=0), 220),
        (F(eyes="surprised", mouth="o", arms="out"), 500),
        (F(eyes="blink", mouth="neutral"), 120),
    ]},
    "talk": {"loop": True, "frames": [
        (F(mouth="open"), 120), (F(mouth="neutral"), 110),
        (F(mouth="smile"), 120), (F(mouth="open"), 100),
        (F(mouth="neutral", eyes="blink"), 100), (F(mouth="open"), 120),
    ]},
    "think": {"loop": True, "frames": [
        (F(eyes="side", mouth="neutral", arms="together"), 700),
        (F(eyes="side", mouth="neutral", arms="together", head_dx=1), 700),
    ]},
    "sleep": {"loop": True, "frames": [
        (F(eyes="blink", mouth="neutral", arms="together", head_dy=1), 900),
        (F(eyes="blink", mouth="o", arms="together", head_dy=1, body_dy=1), 900),
    ]},
    "hop": {"loop": True, "frames": [
        (F(eyes="happy", mouth="open", arms="out_up", legs="tuck"), 1000),
    ]},
    "push": {"loop": True, "frames": [
        (F(view="back", arms="out", legs="step"), 160),
        (F(view="back", arms="out_up", legs="stand", body_dy=1), 120),
        (F(view="back", arms="out", legs="step_r"), 160),
        (F(view="back", arms="out_up", legs="stand", body_dy=1), 120),
    ]},
}

REACTIONS = ["jump", "wave", "heart", "shy"]


def export_sheet(path: str, scale: int = 4) -> None:
    from PIL import Image

    names = list(ANIMATIONS)
    cols = max(len(ANIMATIONS[n]["frames"]) for n in names)
    cols = min(cols, 9)
    pad = 2
    sheet = Image.new("RGBA", ((W + pad) * cols, (H + pad) * len(names)), (235, 238, 245, 255))
    for r, name in enumerate(names):
        for c, (fr, _) in enumerate(ANIMATIONS[name]["frames"][:cols]):
            img = Image.frombytes("RGBA", (W, H), render_rgba(compose(fr)))
            sheet.alpha_composite(img, (c * (W + pad), r * (H + pad)))
    sheet = sheet.resize((sheet.width * scale, sheet.height * scale), Image.NEAREST)
    sheet.save(path)


if __name__ == "__main__":
    import os
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "sprites")
    os.makedirs(out, exist_ok=True)
    target = os.path.join(out, "preview_sheet.png")
    export_sheet(target)
    print("Saved", target)
