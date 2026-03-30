# Whisper Dictation

System-wide speech-to-text dictation for Linux using OpenAI's Whisper model running locally.

**Hold a hotkey combo to record, release to transcribe and paste.**

## Tested Environment

Developed and tested on:
- **Ubuntu 25.10** (Questing Quetzal)
- **GNOME 48 / Mutter** (Wayland session)
- **Ptyxis** terminal (GNOME's native Wayland terminal)

> **Note:** This has not been extensively tested on other desktop environments or
> compositors. That said, the setup script detects Wayland vs X11 and installs
> the appropriate tools, so it should work on most Linux desktops. Contributions
> and bug reports for other environments are welcome.

## Features

- Runs entirely locally — no API keys or internet required (after first model download)
- Works system-wide on Wayland and X11
- Clipboard-paste insertion — avoids issues with apps that intercept individual key events
- Multi-key hotkey combos (e.g. Right Shift + Right Super)
- Uses `faster-whisper` for optimized local transcription
- Configurable model size, hotkey, and language
- Single-file script with inline dependencies managed by [uv](https://docs.astral.sh/uv/)

## Quick Start

```bash
# 1. Run the setup script (installs system packages, Python deps, permissions)
chmod +x setup.sh
./setup.sh

# 2. Log out and log back in (required for 'input' group permissions)

# 3. Start dictating!
./dictation.py
```

## Usage

```bash
# Default: Right Shift + Right Super, base model, auto-detect language
./dictation.py

# Custom hotkey (single key)
./dictation.py --hotkey KEY_SCROLLLOCK

# Custom hotkey (multi-key combo, joined with +)
./dictation.py --hotkey KEY_RIGHTSHIFT+KEY_RIGHTMETA

# Larger model (more accurate, slower)
./dictation.py --model small
./dictation.py --model medium

# Force a specific language
./dictation.py --language en

# Debug mode — verbose logs for troubleshooting
./dictation.py --debug

# List available hotkey names
./dictation.py --list-keys
```

## Model Sizes

| Model    | Size   | Speed   | Accuracy |
|----------|--------|---------|----------|
| tiny     | ~40MB  | Fastest | Lower    |
| base     | ~140MB | Fast    | Good     |
| small    | ~460MB | Medium  | Better   |
| medium   | ~1.5GB | Slow    | Great    |
| large-v3 | ~3GB   | Slowest | Best     |

The first run downloads the model automatically (may take a few minutes).

## How It Works

1. **Keyboard capture** — `evdev` listens for global hotkey events at the Linux input
   subsystem level (requires `input` group membership).

2. **Audio recording** — `sounddevice` + PortAudio captures microphone input into a
   numpy buffer while the hotkey is held.

3. **Transcription** — `faster-whisper` (CTranslate2-optimized Whisper) transcribes the
   audio locally. VAD filtering strips silence automatically.

4. **Text insertion** — the transcribed text is copied to the system clipboard and then
   pasted into the focused window via a simulated Ctrl+Shift+V keystroke:

   | Session  | Clipboard tool | Paste keystroke tool | Notes |
   |----------|---------------|---------------------|-------|
   | Wayland  | `wl-copy`     | `ydotool key`       | ydotool uses Linux uinput — the only method that reaches native Wayland windows on GNOME/Mutter |
   | X11      | `xclip`       | `xdotool key`       | Standard X11 approach |

### Why clipboard paste instead of typing?

Some terminal-based apps (notably **Claude Code**) intercept rapid individual space
key events (to trigger voice chat mode). Character-by-character typing via `ydotool type`
causes spaces to be swallowed. Clipboard paste delivers the entire text as a single
block, bypassing this issue.

### Why ydotool on Wayland?

On GNOME/Mutter Wayland sessions:
- **wtype** requires the `wlr-virtual-keyboard-v1` protocol, which GNOME does not implement (only wlroots-based compositors like Sway/Hyprland support it).
- **xdotool** uses the X11 protocol, so it can only reach XWayland windows, not native Wayland apps.
- **ydotool** operates at the Linux kernel level (uinput), creating a virtual input device that the compositor treats as a real keyboard. This works with **all** windows regardless of toolkit or protocol.

## Run as a Background Service

```bash
# Copy the service file
mkdir -p ~/.config/systemd/user
cp whisper-dictation.service ~/.config/systemd/user/

# Enable and start
systemctl --user daemon-reload
systemctl --user enable whisper-dictation
systemctl --user start whisper-dictation

# Check status / view logs
systemctl --user status whisper-dictation
journalctl --user -u whisper-dictation -f
```

## Troubleshooting

### "No keyboard found" error

Your user needs to be in the `input` group:
```bash
sudo usermod -aG input $USER
# Log out and log back in
```

### Text not appearing after transcription

Run with `--debug` to see what's happening:
```bash
./dictation.py --debug
```

Check that the required tools are installed:
```bash
# Wayland
which wl-copy ydotool

# X11
which xclip xdotool
```

If tools are missing, run `./setup.sh` again.

### Hotkey conflicts with desktop environment

The default Right Super key may conflict with GNOME Activities. Use a combo instead:
```bash
./dictation.py --hotkey KEY_RIGHTSHIFT+KEY_RIGHTMETA
```

Or pick a dedicated key:
```bash
./dictation.py --hotkey KEY_SCROLLLOCK
./dictation.py --hotkey KEY_F9
```

### Audio not working

Check your microphone:
```bash
python3 -c "import sounddevice; print(sounddevice.query_devices())"
```

## Dependencies

**System packages** (installed by `setup.sh`):

| Package          | Purpose                           | Session   |
|------------------|-----------------------------------|-----------|
| `portaudio19-dev`| Audio capture                     | Both      |
| `libsndfile1`    | Audio processing                  | Both      |
| `wl-clipboard`   | Clipboard access (`wl-copy`)      | Wayland   |
| `ydotool`        | Keystroke simulation via uinput   | Wayland   |
| `xclip`          | Clipboard access                  | X11       |
| `xdotool`        | Keystroke simulation via X11      | X11       |

**Python packages** (managed inline by uv, no venv needed):
- `faster-whisper` — optimized Whisper implementation
- `sounddevice` — audio recording
- `numpy` — audio buffer handling
- `evdev` — keyboard event capture

## License

[WTFPL](LICENSE) — Do What The Fuck You Want To Public License
