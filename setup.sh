#!/bin/bash
#
# Setup script for Whisper Dictation
#
# Installs the correct system packages for the current display server
# (Wayland or X11) and ensures the user has permission to read keyboard events.
#
# Wayland (GNOME, etc.):  wl-clipboard + ydotool
# X11:                     xclip + xdotool
#
# See README.md for background on why these specific tools are needed.
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Whisper Dictation Setup ==="
echo

# -- uv (Python script runner) ------------------------------------------
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    echo "uv installed! You may need to restart your shell or source your profile."
fi

# -- Detect display server -----------------------------------------------
SESSION_TYPE="${XDG_SESSION_TYPE:-unknown}"
echo "Detected session type: $SESSION_TYPE"
echo

# -- Core system libraries (audio capture) --------------------------------
echo "Installing core dependencies..."
sudo apt update
sudo apt install -y \
    portaudio19-dev \
    libsndfile1

# -- Display-server-specific text-input tools -----------------------------
#
# Wayland (GNOME/Mutter):
#   wl-clipboard  — CLI clipboard access (wl-copy / wl-paste)
#   ydotool       — simulates keystrokes via Linux uinput; the only tool
#                   that can reach native Wayland windows on GNOME (wtype
#                   requires the wlr virtual-keyboard protocol which GNOME
#                   does not implement; xdotool only reaches XWayland apps)
#
# X11:
#   xclip         — CLI clipboard access
#   xdotool       — simulates keystrokes via the X11 protocol
#
if [ "$SESSION_TYPE" = "wayland" ]; then
    echo "Installing Wayland tools (wl-clipboard, ydotool)..."
    sudo apt install -y wl-clipboard ydotool
elif [ "$SESSION_TYPE" = "x11" ]; then
    echo "Installing X11 tools (xclip, xdotool)..."
    sudo apt install -y xclip xdotool
else
    echo "Unknown session type — installing tools for both Wayland and X11..."
    sudo apt install -y wl-clipboard ydotool xclip xdotool
fi

# -- Clean up stale ydotoold service if present ---------------------------
# Ubuntu's ydotool 0.1.8 package does not ship a ydotoold binary (that was
# added in v1.0+). An earlier version of this setup script created a systemd
# service pointing at /usr/bin/ydotoold which doesn't exist, causing a
# crash loop. Remove it — ydotool 0.1.8 works fine in direct mode.
if [ -f /etc/systemd/system/ydotool.service ]; then
    echo
    echo "Removing stale ydotoold service..."
    sudo systemctl stop ydotool 2>/dev/null || true
    sudo systemctl disable ydotool 2>/dev/null || true
    sudo rm -f /etc/systemd/system/ydotool.service
    sudo systemctl daemon-reload
fi

# -- Keyboard access permissions -----------------------------------------
echo
echo "Adding $USER to 'input' group (needed to read keyboard events via evdev)..."
sudo usermod -aG input "$USER"

# -- Make the script executable ------------------------------------------
chmod +x "$SCRIPT_DIR/dictation.py"

# -- Pre-install Python dependencies via uv ------------------------------
echo
echo "Pre-installing Python dependencies..."
uv run --script "$SCRIPT_DIR/dictation.py" --help > /dev/null 2>&1 || true

# -- Done ----------------------------------------------------------------
echo
echo "=== Setup Complete! ==="
echo
echo "IMPORTANT: Log out and log back in for the 'input' group to take effect."
echo
echo "Usage:"
echo "  $SCRIPT_DIR/dictation.py                                          # Start with defaults"
echo "  $SCRIPT_DIR/dictation.py --hotkey KEY_SCROLLLOCK                  # Single-key hotkey"
echo "  $SCRIPT_DIR/dictation.py --hotkey KEY_RIGHTSHIFT+KEY_RIGHTMETA    # Multi-key combo"
echo "  $SCRIPT_DIR/dictation.py --model small                            # More accurate model"
echo "  $SCRIPT_DIR/dictation.py --list-keys                              # List available hotkeys"
echo
echo "See README.md for more details."
