#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "faster-whisper>=0.10.0",
#     "sounddevice>=0.4.6",
#     "numpy>=1.24.0",
#     "evdev>=1.6.0",
# ]
# ///
"""
Whisper Dictation - System-wide speech-to-text for Linux (Wayland)

Hold a hotkey to record, release to transcribe and type.
Uses local Whisper model for transcription and ydotool for text insertion.
"""

import argparse
import asyncio
import io
import os
import signal
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path

import evdev
import numpy as np
import sounddevice as sd

# Lazy load whisper to speed up startup
_whisper_model = None


def get_whisper_model(model_size: str = "base"):
    """Load whisper model lazily."""
    global _whisper_model
    if _whisper_model is None:
        print(f"Loading Whisper model '{model_size}'... (first run may take a minute)")
        from faster_whisper import WhisperModel

        # Use CPU by default, can be changed to "cuda" if GPU available
        _whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
        print("Model loaded!")
    return _whisper_model


class DictationService:
    """Main dictation service that handles hotkey, recording, and transcription."""

    def __init__(
        self,
        hotkey: str = "KEY_RIGHTMETA",  # Right Super/Windows key
        model_size: str = "base",
        sample_rate: int = 16000,
        language: str = None,  # Auto-detect if None
    ):
        self.hotkey = hotkey
        self.model_size = model_size
        self.sample_rate = sample_rate
        self.language = language

        self.recording = False
        self.audio_data = []
        self.stream = None
        self.keyboard = None

    def find_keyboard(self) -> evdev.InputDevice:
        """Find a keyboard device."""
        devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
        for device in devices:
            caps = device.capabilities()
            # Check if device has key events and looks like a keyboard
            if evdev.ecodes.EV_KEY in caps:
                keys = caps[evdev.ecodes.EV_KEY]
                # Check for common keyboard keys
                if evdev.ecodes.KEY_A in keys and evdev.ecodes.KEY_ENTER in keys:
                    return device
        raise RuntimeError("No keyboard found! Make sure you have permission to access /dev/input/*")

    def start_recording(self):
        """Start audio recording."""
        if self.recording:
            return

        self.recording = True
        self.audio_data = []

        def callback(indata, frames, time, status):
            if status:
                print(f"Audio status: {status}", file=sys.stderr)
            if self.recording:
                self.audio_data.append(indata.copy())

        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype=np.float32,
            callback=callback,
        )
        self.stream.start()
        print("Recording...")

    def stop_recording(self) -> np.ndarray:
        """Stop recording and return audio data."""
        if not self.recording:
            return None

        self.recording = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        if not self.audio_data:
            return None

        audio = np.concatenate(self.audio_data, axis=0).flatten()
        print(f"Recorded {len(audio) / self.sample_rate:.1f} seconds")
        return audio

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe audio using Whisper."""
        if audio is None or len(audio) < self.sample_rate * 0.5:  # Less than 0.5 seconds
            print("Recording too short, skipping...")
            return ""

        print("Transcribing...")
        model = get_whisper_model(self.model_size)

        segments, info = model.transcribe(
            audio,
            language=self.language,
            beam_size=5,
            vad_filter=True,  # Filter out non-speech
        )

        text = " ".join(segment.text for segment in segments).strip()
        print(f"Transcribed: {text}")
        return text

    def type_text(self, text: str):
        """Type text using ydotool."""
        if not text:
            return

        try:
            # ydotool type command
            subprocess.run(
                ["ydotool", "type", "--", text],
                check=True,
                capture_output=True,
            )
        except FileNotFoundError:
            print("Error: ydotool not found. Please install it:", file=sys.stderr)
            print("  sudo apt install ydotool", file=sys.stderr)
            print("  sudo systemctl enable --now ydotool", file=sys.stderr)
        except subprocess.CalledProcessError as e:
            print(f"Error typing text: {e.stderr.decode()}", file=sys.stderr)

    def run(self):
        """Main event loop."""
        print(f"Whisper Dictation starting...")
        print(f"  Model: {self.model_size}")
        print(f"  Hotkey: {self.hotkey}")
        print(f"  Language: {self.language or 'auto-detect'}")
        print()

        # Pre-load the model
        get_whisper_model(self.model_size)

        try:
            self.keyboard = self.find_keyboard()
            print(f"Using keyboard: {self.keyboard.name}")
            print(f"\nHold {self.hotkey} to dictate, release to transcribe.")
            print("Press Ctrl+C to exit.\n")
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            print("\nTip: Add your user to the 'input' group:", file=sys.stderr)
            print("  sudo usermod -aG input $USER", file=sys.stderr)
            print("  (then log out and back in)", file=sys.stderr)
            sys.exit(1)

        hotkey_code = getattr(evdev.ecodes, self.hotkey, None)
        if hotkey_code is None:
            print(f"Error: Unknown key '{self.hotkey}'", file=sys.stderr)
            print("Use a key name from: https://python-evdev.readthedocs.io/en/latest/apidoc.html#evdev.ecodes", file=sys.stderr)
            sys.exit(1)

        try:
            for event in self.keyboard.read_loop():
                if event.type == evdev.ecodes.EV_KEY and event.code == hotkey_code:
                    if event.value == 1:  # Key pressed
                        self.start_recording()
                    elif event.value == 0:  # Key released
                        audio = self.stop_recording()
                        text = self.transcribe(audio)
                        self.type_text(text)
        except KeyboardInterrupt:
            print("\nExiting...")
        finally:
            if self.stream:
                self.stream.stop()
                self.stream.close()


def list_keys():
    """List available key names."""
    print("Available key names (use with --hotkey):\n")
    keys = [k for k in dir(evdev.ecodes) if k.startswith("KEY_")]

    # Common useful keys
    common = [
        "KEY_RIGHTMETA", "KEY_LEFTMETA",  # Super/Windows keys
        "KEY_RIGHTALT", "KEY_LEFTALT",
        "KEY_RIGHTCTRL", "KEY_LEFTCTRL",
        "KEY_SCROLLLOCK", "KEY_PAUSE",
        "KEY_INSERT", "KEY_PRINT",
        "KEY_F1", "KEY_F2", "KEY_F3", "KEY_F4",
        "KEY_F5", "KEY_F6", "KEY_F7", "KEY_F8",
        "KEY_F9", "KEY_F10", "KEY_F11", "KEY_F12",
    ]

    print("Common hotkey choices:")
    for key in common:
        if key in keys:
            print(f"  {key}")
    print("\nAll keys: https://python-evdev.readthedocs.io/en/latest/apidoc.html#evdev.ecodes")


def main():
    parser = argparse.ArgumentParser(
        description="System-wide dictation using Whisper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Use defaults (Right Super key, base model)
  %(prog)s --hotkey KEY_SCROLLLOCK  # Use Scroll Lock as hotkey
  %(prog)s --model small            # Use small model (more accurate)
  %(prog)s --language en            # Force English language
  %(prog)s --list-keys              # Show available hotkey names
        """,
    )
    parser.add_argument(
        "--hotkey",
        default="KEY_RIGHTMETA",
        help="Key to hold for recording (default: KEY_RIGHTMETA)",
    )
    parser.add_argument(
        "--model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Whisper model size (default: base)",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Language code (e.g., en, es, fr). Auto-detect if not specified.",
    )
    parser.add_argument(
        "--list-keys",
        action="store_true",
        help="List available hotkey names and exit",
    )

    args = parser.parse_args()

    if args.list_keys:
        list_keys()
        return

    service = DictationService(
        hotkey=args.hotkey,
        model_size=args.model,
        language=args.language,
    )
    service.run()


if __name__ == "__main__":
    main()
