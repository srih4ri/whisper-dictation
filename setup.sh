#!/bin/bash
#
# Setup script for Whisper Dictation
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Whisper Dictation Setup ==="
echo

# Check for uv
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    echo "uv installed! You may need to restart your shell or source your profile."
fi

# Install system dependencies
echo "Installing system dependencies..."
sudo apt update
sudo apt install -y \
    portaudio19-dev \
    ydotool \
    libsndfile1

# Setup ydotool daemon
# Ubuntu 24.04 ships an older ydotool (0.1.8) without systemd service
# We need to create one manually
echo
echo "Setting up ydotool daemon..."

# Create systemd service for ydotoold if it doesn't exist
if ! systemctl list-unit-files | grep -q ydotool.service; then
    echo "Creating ydotool systemd service..."
    sudo tee /etc/systemd/system/ydotool.service > /dev/null << 'YDOSVC'
[Unit]
Description=ydotool daemon
Documentation=man:ydotool(1)

[Service]
Type=simple
ExecStart=/usr/bin/ydotoold
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
YDOSVC
    sudo systemctl daemon-reload
fi

sudo systemctl enable ydotool
sudo systemctl start ydotool

# Add user to input group for keyboard access
echo
echo "Adding $USER to 'input' group for keyboard access..."
sudo usermod -aG input "$USER"

# Make the script executable
chmod +x "$SCRIPT_DIR/dictation.py"

# Pre-install Python dependencies via uv
echo
echo "Pre-installing Python dependencies..."
uv run --script "$SCRIPT_DIR/dictation.py" --help > /dev/null 2>&1 || true

echo
echo "=== Setup Complete! ==="
echo
echo "IMPORTANT: You need to log out and log back in for the 'input' group to take effect."
echo
echo "Usage:"
echo "  $SCRIPT_DIR/dictation.py                    # Start with defaults"
echo "  $SCRIPT_DIR/dictation.py --hotkey KEY_F9    # Use F9 as hotkey"
echo "  $SCRIPT_DIR/dictation.py --model small      # Use more accurate model"
echo "  $SCRIPT_DIR/dictation.py --list-keys        # List available hotkeys"
echo
echo "To run as a background service, see: $SCRIPT_DIR/README.md"
