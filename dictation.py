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
Whisper Dictation - System-wide speech-to-text for Linux (Wayland + X11)

Hold a hotkey combo to record, release to transcribe and type.
Uses a local Whisper model for transcription so nothing leaves your machine.

Text insertion strategy:
  The transcribed text is copied to the clipboard and pasted via a simulated
  Ctrl+Shift+V keystroke. This clipboard-paste approach is used instead of
  character-by-character typing (ydotool type) because some TUI apps — notably
  Claude Code — intercept individual space key events and never deliver them to
  the input field.

  On Wayland the only tool that can inject keystrokes into *all* windows
  (including native Wayland apps like Ptyxis, Kitty, etc.) is ydotool, which
  operates at the Linux uinput level beneath the compositor. Tools like wtype
  require the wlr-virtual-keyboard-v1 protocol which GNOME/Mutter does not
  implement, and xdotool can only reach XWayland windows.

  On X11, xdotool + xclip is used instead.
"""

import argparse
import logging
import os
import shutil
import subprocess
import sys
import time

import evdev
import numpy as np
import sounddevice as sd

log = logging.getLogger("whisper-dictation")

_whisper_model = None


def get_whisper_model(model_size: str = "base"):
    """Load the whisper model on first call, then return the cached instance."""
    global _whisper_model
    if _whisper_model is None:
        log.info("Loading Whisper model '%s'... (first run may take a minute)", model_size)
        from faster_whisper import WhisperModel

        _whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
        log.info("Model loaded!")
    return _whisper_model


# ---------------------------------------------------------------------------
# Tool detection — runs once at startup, result is cached for the session
# ---------------------------------------------------------------------------

def _detect_session_type() -> str:
    """Return 'wayland', 'x11', or 'unknown' based on environment variables."""
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def _detect_typing_method(session_type: str) -> str:
    """Choose the best clipboard-copy + paste-keystroke combo for this system.

    Returns one of:
      "ydotool-paste"  — wl-copy (clipboard) + ydotool key (paste keystroke)
                         Works on any Wayland compositor because ydotool uses
                         the kernel uinput subsystem, not a Wayland protocol.
      "xdotool-x"      — xclip (clipboard) + xdotool key (paste keystroke)
                         Standard X11 approach.
      "ydotool"         — ydotool type (character-by-character fallback)
                         Spaces may be swallowed by some apps (e.g. Claude Code).
    """
    has_wl_copy = shutil.which("wl-copy") is not None
    has_xclip = shutil.which("xclip") is not None
    has_xdotool = shutil.which("xdotool") is not None
    has_ydotool = shutil.which("ydotool") is not None

    log.debug("Tool detection: wl-copy=%s xclip=%s xdotool=%s ydotool=%s",
              has_wl_copy, has_xclip, has_xdotool, has_ydotool)

    # --- Wayland --------------------------------------------------------
    if session_type == "wayland":
        if has_wl_copy and has_ydotool:
            return "ydotool-paste"

        # Tell the user exactly what's missing
        if not has_wl_copy:
            log.warning("⚠️  wl-clipboard not found — needed for clipboard access on Wayland")
            log.warning("   Install: sudo apt install wl-clipboard")
        if not has_ydotool:
            log.warning("⚠️  ydotool not found — needed for simulating paste keystrokes")
            log.warning("   Install: sudo apt install ydotool")

    # --- X11 ------------------------------------------------------------
    if session_type == "x11":
        if has_xclip and has_xdotool:
            return "xdotool-x"

        missing = []
        if not has_xclip:
            missing.append("xclip")
        if not has_xdotool:
            missing.append("xdotool")
        if missing:
            log.warning("⚠️  Missing: %s", ", ".join(missing))
            log.warning("   Install: sudo apt install %s", " ".join(missing))

    # --- Last resort: ydotool type (character-by-character) -------------
    if has_ydotool:
        log.warning("⚠️  Falling back to ydotool type — spaces may be eaten by some apps")
        return "ydotool"

    log.error("⛔ No text input tool found! Run ./setup.sh to install dependencies.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

class DictationService:
    """Listens for a hotkey combo, records audio, transcribes, and pastes."""

    def __init__(
        self,
        hotkey: str = "KEY_RIGHTSHIFT+KEY_RIGHTMETA",
        model_size: str = "base",
        sample_rate: int = 16000,
        language: str = None,
    ):
        self.hotkey = hotkey
        self.model_size = model_size
        self.sample_rate = sample_rate
        self.language = language

        self.recording = False
        self.audio_data = []
        self.stream = None
        self.keyboard = None

        # Populated once by _detect_tools() at startup
        self.session_type = None
        self.typing_method = None

        # wl-copy runs as a long-lived process (clipboard server); we keep a
        # reference so we can kill the previous instance before starting a new one.
        self._wl_copy_proc = None

    # -- Setup (called once) ---------------------------------------------

    def _parse_hotkey(self) -> list[int]:
        """Parse 'KEY_A+KEY_B' into a list of evdev key codes."""
        key_names = [k.strip() for k in self.hotkey.split("+")]
        codes = []
        for name in key_names:
            code = getattr(evdev.ecodes, name, None)
            if code is None:
                log.error("⛔ Unknown key '%s'", name)
                log.error("   Run ./dictation.py --list-keys to see valid names")
                sys.exit(1)
            codes.append(code)
        return codes

    def _detect_tools(self):
        """Detect display server and available CLI tools. Called once at startup."""
        self.session_type = _detect_session_type()
        self.typing_method = _detect_typing_method(self.session_type)
        log.info("Session: %s | Typing method: %s", self.session_type, self.typing_method)

    def _find_keyboard(self) -> evdev.InputDevice:
        """Find the first device that looks like a physical keyboard."""
        devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
        for device in devices:
            caps = device.capabilities()
            if evdev.ecodes.EV_KEY in caps:
                keys = caps[evdev.ecodes.EV_KEY]
                # A real keyboard will have letter keys and Enter
                if evdev.ecodes.KEY_A in keys and evdev.ecodes.KEY_ENTER in keys:
                    return device
        raise RuntimeError("No keyboard found! Make sure you have permission to access /dev/input/*")

    # -- Recording -------------------------------------------------------

    def start_recording(self):
        """Open the microphone and start buffering audio."""
        if self.recording:
            return

        self.recording = True
        self.audio_data = []

        def callback(indata, frames, time, status):
            if status:
                log.warning("Audio status: %s", status)
            if self.recording:
                self.audio_data.append(indata.copy())

        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype=np.float32,
            callback=callback,
        )
        self.stream.start()
        log.info("Recording...")

    def stop_recording(self) -> np.ndarray:
        """Stop the microphone and return the recorded audio as a numpy array."""
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
        log.info("Recorded %.1f seconds", len(audio) / self.sample_rate)
        return audio

    # -- Transcription ---------------------------------------------------

    def transcribe(self, audio: np.ndarray) -> str:
        """Run Whisper on the recorded audio and return the transcribed text."""
        if audio is None or len(audio) < self.sample_rate * 0.5:
            log.info("Recording too short, skipping...")
            return ""

        log.info("Transcribing...")
        model = get_whisper_model(self.model_size)

        segments, _info = model.transcribe(
            audio,
            language=self.language,
            beam_size=5,
            vad_filter=True,  # strip silence / non-speech
        )

        text = " ".join(segment.text for segment in segments).strip()
        log.info("Transcribed: %s", text)
        return text

    # -- Text insertion --------------------------------------------------

    def type_text(self, text: str):
        """Insert text into the focused window using the method chosen at startup.

        The preferred path (ydotool-paste / xdotool-x) copies the text to the
        system clipboard and then simulates Ctrl+Shift+V so the terminal pastes
        it as a single block. This avoids per-character key events that some
        apps intercept.
        """
        if not text:
            return

        log.debug("type_text: method=%s len=%d", self.typing_method, len(text))

        if self.typing_method == "ydotool-paste":
            self._paste_wayland(text)
        elif self.typing_method == "xdotool-x":
            self._paste_x11(text)
        else:
            self._type_fallback(text)

        log.debug("type_text: done")

    def _paste_wayland(self, text: str):
        """Copy to Wayland clipboard, then simulate Ctrl+Shift+V via ydotool.

        wl-copy runs as a long-lived process that serves clipboard read requests;
        we start it with Popen (non-blocking) and kill the previous instance each
        time so they don't accumulate.

        ydotool key is run with --delay 200 (ms) to give its temporary uinput
        virtual keyboard time to be registered by the compositor before the key
        events are sent.
        """
        if self._wl_copy_proc:
            self._wl_copy_proc.kill()
            self._wl_copy_proc.wait()

        log.debug("wl-copy: setting clipboard...")
        self._wl_copy_proc = subprocess.Popen(
            ["wl-copy", "--", text],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # Small delay to let wl-copy register with the Wayland compositor
        time.sleep(0.1)

        log.debug("ydotool key: sending Ctrl+Shift+V...")
        result = subprocess.run(
            ["ydotool", "key", "--delay", "200", "ctrl+shift+v"],
            capture_output=True,
        )
        log.debug("ydotool key: exit=%d stderr=%r", result.returncode, result.stderr)

    def _paste_x11(self, text: str):
        """Copy to X11 clipboard via xclip, then simulate Ctrl+Shift+V via xdotool."""
        log.debug("xclip: setting clipboard...")
        subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=text.encode(), check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.05)

        log.debug("xdotool key: sending Ctrl+Shift+V...")
        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", "ctrl+shift+v"],
            check=True, capture_output=True,
        )

    def _type_fallback(self, text: str):
        """Character-by-character typing via ydotool (last resort).

        This works everywhere but spaces may be swallowed by apps that intercept
        the space key (e.g. Claude Code uses it to activate voice chat).
        """
        log.debug("ydotool type: typing %d chars...", len(text))
        subprocess.run(["ydotool", "type", "--", text], check=True, capture_output=True)

    # -- Event loop ------------------------------------------------------

    def run(self):
        """Boot up and enter the main hotkey event loop."""
        self._detect_tools()

        log.info("Whisper Dictation starting...")
        log.info("  Model: %s", self.model_size)
        log.info("  Hotkey: %s", self.hotkey)
        log.info("  Language: %s", self.language or "auto-detect")

        get_whisper_model(self.model_size)

        try:
            self.keyboard = self._find_keyboard()
            log.info("Using keyboard: %s", self.keyboard.name)
        except RuntimeError as e:
            log.error("⛔ %s", e)
            log.error("   Add your user to the 'input' group:")
            log.error("     sudo usermod -aG input $USER")
            log.error("   Then log out and back in.")
            sys.exit(1)

        hotkey_codes = self._parse_hotkey()
        held_keys = set()  # tracks which hotkey keys are currently pressed

        log.info("")
        log.info("Hold %s to dictate, release to transcribe.", self.hotkey)
        log.info("Press Ctrl+C to exit.")
        log.info("")

        try:
            for event in self.keyboard.read_loop():
                if event.type != evdev.ecodes.EV_KEY:
                    continue
                if event.code not in hotkey_codes:
                    continue

                if event.value == 1:  # key down
                    held_keys.add(event.code)
                    log.debug("Key down: %s held=%s", evdev.ecodes.KEY[event.code], held_keys)
                    # Start recording once ALL combo keys are held simultaneously
                    if held_keys == set(hotkey_codes):
                        self.start_recording()

                elif event.value == 0:  # key up
                    held_keys.discard(event.code)
                    log.debug("Key up: %s held=%s", evdev.ecodes.KEY[event.code], held_keys)
                    # Stop recording when ANY combo key is released
                    if self.recording:
                        audio = self.stop_recording()
                        text = self.transcribe(audio)
                        try:
                            self.type_text(text)
                        except Exception:
                            log.exception("⚠️  type_text failed")

        except KeyboardInterrupt:
            log.info("Exiting...")
        finally:
            if self.stream:
                self.stream.stop()
                self.stream.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def list_keys():
    """Print hotkey names useful for --hotkey."""
    print("Available key names (use with --hotkey):\n")
    keys = [k for k in dir(evdev.ecodes) if k.startswith("KEY_")]

    common = [
        "KEY_RIGHTMETA", "KEY_LEFTMETA",
        "KEY_RIGHTALT", "KEY_LEFTALT",
        "KEY_RIGHTCTRL", "KEY_LEFTCTRL",
        "KEY_RIGHTSHIFT", "KEY_LEFTSHIFT",
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
    print("\nCombine keys with +: --hotkey KEY_RIGHTSHIFT+KEY_RIGHTMETA")
    print("All keys: https://python-evdev.readthedocs.io/en/latest/apidoc.html#evdev.ecodes")


def main():
    parser = argparse.ArgumentParser(
        description="System-wide dictation using Whisper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                            # Defaults (Right Shift + Right Super, base model)
  %(prog)s --hotkey KEY_SCROLLLOCK                    # Single-key hotkey
  %(prog)s --hotkey KEY_RIGHTSHIFT+KEY_RIGHTMETA      # Multi-key combo
  %(prog)s --model small                              # More accurate model
  %(prog)s --language en                              # Force English
  %(prog)s --debug                                    # Verbose logging
  %(prog)s --list-keys                                # Show available key names
        """,
    )
    parser.add_argument(
        "--hotkey",
        default="KEY_RIGHTSHIFT+KEY_RIGHTMETA",
        help="Key(s) to hold for recording, combine with + (default: KEY_RIGHTSHIFT+KEY_RIGHTMETA)",
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
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

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
