# Whisper Dictation

System-wide speech-to-text dictation for Ubuntu/Linux using OpenAI's Whisper model (running locally).

**Hold a hotkey to record, release to transcribe and type.**

## Features

- Runs entirely locally - no API keys or internet required
- Works system-wide on Wayland (and X11)
- Uses `faster-whisper` for optimized transcription
- Configurable hotkey and model size
- Auto-detects language (or can be set explicitly)

## Quick Start

```bash
# Run the setup script
chmod +x setup.sh
./setup.sh

# Log out and log back in (required for input group permissions)

# Start dictating
./dictate
```

## Usage

```bash
# Default: Right Super key, base model
./dictate

# Use a different hotkey
./dictate --hotkey KEY_SCROLLLOCK
./dictate --hotkey KEY_F9

# Use a larger model (more accurate, slower)
./dictate --model small
./dictate --model medium

# Force a specific language
./dictate --language en
./dictate --language es

# List available hotkeys
./dictate --list-keys
```

## Model Sizes

| Model | Size | Speed | Accuracy |
|-------|------|-------|----------|
| tiny | ~40MB | Fastest | Lower |
| base | ~140MB | Fast | Good |
| small | ~460MB | Medium | Better |
| medium | ~1.5GB | Slow | Great |
| large-v3 | ~3GB | Slowest | Best |

The first run will download the model (may take a few minutes).

## Run as a Background Service

To start dictation automatically at login:

```bash
# Copy the service file
mkdir -p ~/.config/systemd/user
cp whisper-dictation.service ~/.config/systemd/user/

# Enable and start
systemctl --user daemon-reload
systemctl --user enable whisper-dictation
systemctl --user start whisper-dictation

# Check status
systemctl --user status whisper-dictation

# View logs
journalctl --user -u whisper-dictation -f
```

## Troubleshooting

### "No keyboard found" error

Add your user to the `input` group:
```bash
sudo usermod -aG input $USER
# Then log out and log back in
```

### "ydotool not found" error

Install and enable ydotool:
```bash
sudo apt install ydotool
sudo systemctl enable --now ydotool
```

### Text not appearing

Make sure the ydotool daemon is running:
```bash
sudo systemctl status ydotool
# If not running:
sudo systemctl start ydotool
```

### Audio not working

Check your microphone is detected:
```bash
# List audio devices
python3 -c "import sounddevice; print(sounddevice.query_devices())"
```

Install PulseAudio/PipeWire if needed:
```bash
sudo apt install pulseaudio pavucontrol
```

## Dependencies

**System packages:**
- `ydotool` - Text insertion on Wayland
- `portaudio19-dev` - Audio capture
- `libsndfile1` - Audio processing

**Python packages:**
- `faster-whisper` - Optimized Whisper implementation
- `sounddevice` - Audio recording
- `numpy` - Audio processing
- `evdev` - Keyboard event capture

## How It Works

1. **Keyboard capture**: Uses `evdev` to listen for global hotkey events (requires `input` group membership)
2. **Audio recording**: Uses `sounddevice` with PortAudio to capture microphone input
3. **Transcription**: Uses `faster-whisper` (CTranslate2-optimized Whisper) for fast local transcription
4. **Text insertion**: Uses `ydotool` to type the transcribed text into the focused application

## License

MIT
