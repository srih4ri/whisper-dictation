# Whisper Dictation

A voice-to-text dictation tool for Linux that uses a local Whisper model to transcribe speech and types it into any focused application.

## Project Overview

This program captures audio while a hotkey is held, transcribes it using faster-whisper (local LLM), and injects the text into the currently focused application using ydotool.

### Architecture Flow

```
Hold hotkey → Record audio → Transcribe locally → Type text via ydotool
```

## Key Files

| File | Purpose |
|------|---------|
| `dictation.py` | Main application - recording, transcription, text input |
| `dictate` | Bash wrapper that activates venv and runs dictation.py |
| `setup.sh` | Installation script for dependencies |
| `requirements.txt` | Python dependencies |
| `whisper-dictation.service` | Systemd user service for background operation |

## Tech Stack

- **Python 3.12** with virtual environment
- **faster-whisper** - CTranslate2-optimized Whisper for transcription
- **sounddevice** - Audio recording via PortAudio
- **evdev** - Global keyboard hotkey capture
- **ydotool** - Text injection (Wayland/X11 compatible)

## Common Commands

```bash
# Run with defaults (Right Super key, base model)
./dictate

# Different hotkey
./dictate --hotkey KEY_SCROLLLOCK

# More accurate model (slower)
./dictate --model small

# Force language
./dictate --language en

# List available hotkeys
./dictate --list-keys

# Enable as background service
systemctl --user enable --now whisper-dictation.service
```

## Known Issues & Solutions

### Current Issue: ydotool/ydotoold Not Working

**Error:**
```
ydotool: notice: ydotoold backend unavailable (may have latency+delay issues)
terminate called after throwing an instance of 'std::runtime_error'
  what():  failed to open uinput device
```

**Cause:** The ydotoold daemon is not running or doesn't have permissions to access `/dev/uinput`.

**Fixes to try:**

1. **Start ydotoold daemon:**
   ```bash
   sudo systemctl start ydotool
   sudo systemctl enable ydotool
   ```

2. **If systemd service doesn't exist, create it:**
   ```bash
   sudo tee /etc/systemd/system/ydotool.service << 'EOF'
   [Unit]
   Description=ydotool daemon

   [Service]
   ExecStart=/usr/bin/ydotoold

   [Install]
   WantedBy=multi-user.target
   EOF

   sudo systemctl daemon-reload
   sudo systemctl enable --now ydotool
   ```

3. **Check uinput permissions:**
   ```bash
   # Ensure uinput module is loaded
   sudo modprobe uinput

   # Add user to input group
   sudo usermod -aG input $USER
   # Then log out and back in
   ```

4. **Run ydotoold manually (for testing):**
   ```bash
   sudo ydotoold &
   ```

### Other Common Issues

- **"No keyboard device found"** - Add user to `input` group: `sudo usermod -aG input $USER`
- **Audio not recording** - Check microphone: `arecord -l` or `python -c "import sounddevice; print(sounddevice.query_devices())"`
- **Model download slow** - First run downloads the Whisper model (~150MB for base)

## Code Structure

### dictation.py Key Components

- **Lines 29-39**: Lazy model loading (faster-whisper)
- **Lines 62-74**: Keyboard device detection via evdev
- **Lines 75-114**: Audio recording with sounddevice
- **Lines 116-134**: Transcription with VAD filtering
- **Lines 136-153**: Text injection via ydotool subprocess
- **Lines 155-199**: Main event loop

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `--hotkey` | `KEY_RIGHTMETA` | Key to hold while speaking |
| `--model` | `base` | Whisper model size (tiny/base/small/medium/large-v3) |
| `--language` | auto-detect | Force specific language code |
| `--sample-rate` | 16000 | Audio sample rate in Hz |

## Development Notes

- Model runs on CPU with int8 quantization for broad compatibility
- Minimum recording length is 0.5 seconds to filter accidental presses
- Uses beam_size=5 for transcription accuracy
- VAD filter removes silence automatically

## Dependencies

**System packages (via apt):**
- ydotool
- portaudio19-dev
- libsndfile1

**Python packages:**
- faster-whisper>=0.10.0
- sounddevice>=0.4.6
- numpy>=1.24.0
- evdev>=1.6.0
