# animetomogochi

**ZetaBuddy** - Zeta Intelligence on Your Desktop.

A small desktop companion for Windows. Zeta is a pixel-art chibi office girl (red hair with an ahoge, star hair clips, blue glasses, black suit) who lives on top of your windows, walks around the screen, reacts when you poke her and answers questions through OpenRouter. She can also launch apps, games, websites and system settings by name, and move or resize your windows.

![sprites](docs/sprites.png)

## Features

- Frameless transparent always-on-top character, walks along the taskbar or freely around the screen
- Drag and drop with a "hanging" pose, swing and throw physics
- Left click: random reaction (jump, wave, heart, shy) with sound, opens the chat bubble
- Right click: context menu (chat, settings, voice, walking, window actions, emotes, hide, exit)
- Chat bubble with typewriter output and optional voice
- AI answers through any OpenRouter model (OpenAI-compatible API)
- "open telegram", "run cs2 and discord", "open downloads", "open bluetooth settings" - big alias dictionary plus automatic index of installed software (Start menu, Microsoft Store, shortcuts, App Paths, Steam, Epic)
- Understands Russian, English and some Kazakh, case endings, transliteration, wrong keyboard layout and typos
- Window control via Win32: minimize, maximize, center, snap, move, resize, and Zeta can physically push a window across the screen
- Global hotkey `\` (the key above Enter) to hide or show her
- Tray icon, single instance, optional autostart with Windows

## Requirements

- Windows 10/11 (the character itself runs anywhere Qt runs, window control and app launching are Windows only)
- Python 3.10+
- An OpenRouter API key: https://openrouter.ai/keys

## Setup

```bash
git clone git@github.com:loliksudoc/animetomogochi.git
cd animetomogochi
pip install -r requirements.txt
copy .env.example .env
```

Put your key into `.env`:

```
OPENROUTER_API_KEY=sk-or-v1-...
```

The key can also be entered in Settings, it is then stored in `config.json` (ignored by git).

## Running

```bash
python main.py
```

or double-click `ZetaBuddy.pyw` to run it in the background without a console window. Errors are written to `zetabuddy.log`.

Autostart: Settings > Character > "Start with Windows" (adds a value to `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`).

## Controls

| Action | Result |
|---|---|
| Left click | reaction + chat bubble |
| Drag | carry her around, release to drop |
| Right click | menu |
| `\` | hide / show |
| `Esc` in the bubble | close chat |
| Click on the answer | finish typing instantly |

### Chat commands

Launching things works locally, without calling the AI:

```
открой телеграм
запусти кс и дискорд
вруби музыку
open visual studio code
открой загрузки
открой настройки блютуз
```

Slash commands:

```
/help               list of commands
/apps               dictionary and index size
/apps refresh       rescan installed software
/find <name>        show what a query matches
/min /max /restore /center /left /right
/push left  /push right
/move X Y   /size W H
/wave /jump /heart /shy
/clear              reset the conversation
```

Window commands apply to the last active window of another program. The AI can use the same actions through hidden tags like `[[open:youtube]]` or `[[window:minimize]]`. The AI can only open items that exist in the dictionary or the installed index, it cannot run arbitrary paths, and there is intentionally no "close window" action.

## Adding apps to the dictionary

Every line in `catalog/*.txt` is one entry:

```
id | Display name | targets | aliases
my_tool | My Tool | name:My Tool; path:D:\Tools\mytool.exe; url:https://example.com | my tool, mytool, майтул
```

Targets are tried left to right:

| Type | Meaning |
|---|---|
| `name:` | display name in the Start menu / Steam / Epic library |
| `exe:` | executable name found in shortcuts or App Paths |
| `path:` | full path, `%ENV%` variables and `*` globs allowed |
| `uwp:` | Microsoft Store package family name prefix |
| `cmd:` | command from PATH or System32, may include arguments |
| `uri:` | protocol link, e.g. `ms-settings:bluetooth`, `steam://open/main` |
| `shell:` | shell folder, e.g. `shell:Downloads` |
| `steam:` | Steam app id |
| `epic:` | Epic Games app name |
| `url:` | website, used as a fallback when nothing local is found |
| `group:` | list of other ids, the first available one wins |

## Customization

**Sounds.** Default sounds are generated into `assets/sounds` on first start. Replace any of them with your own files using the same names (`click.wav`, `jump.wav`, `wave.wav`, `heart.wav`, `shy.wav`, `bonk.wav`, `speech_sound.wav`).

**Voice.** Answers are voiced in this order of priority:
1. `assets/sounds/voice/voice_*.wav` - random phrases while the text is typed, `react_*.wav` - short lines on click
2. `assets/sounds/voice.mp3` - looped while typing
3. beeps from `speech_sound.wav`

Voice clips are not included in the repository.

**Sprites.** The character is drawn procedurally in `sprites.py`. Any frame can be replaced with a PNG: `assets/sprites/<animation>_<frame>.png`, e.g. `idle_0.png`, `walk_left_2.png` (32x43 or any multiple). Run `python sprites.py` to export a sheet with all frames.

## Project structure

```
main.py            entry point, tray, global hotkey
mascot_ui.py       character, physics, chat bubble, settings, controller
sprites.py         pixel-art layers and animations
ai_client.py       OpenRouter client, command tags parsing
app_launcher.py    command parsing, search, installed software index, launching
window_manager.py  Win32 window control through ctypes
audio_manager.py   sound effects and voice (pygame.mixer)
config.py          settings, .env loading, autostart
catalog/           alias dictionary
assets/            sounds and optional custom sprites
ZetaBuddy.pyw      windowless launcher
```

## Configuration

`config.json` is created when you save settings. Useful keys: `model`, `base_url`, `temperature`, `history_length`, `voice_enabled`, `sfx_enabled`, `volume`, `scale`, `walk_enabled`, `walk_speed`, `physics_mode` (`floor` or `free`), `activity`, `hotkey_enabled`, `typing_speed_ms`.
