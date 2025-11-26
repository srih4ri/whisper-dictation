#!/bin/bash
#
# Setup script for Whisper Dictation
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

echo "=== Whisper Dictation Setup ==="
echo

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed."
    echo "Install with: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi

# Install system dependencies
echo "Installing system dependencies..."
sudo apt update
sudo apt install -y \
    python3-venv \
    python3-pip \
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

# Create virtual environment
echo
echo "Creating Python virtual environment..."
python3 -m venv "$VENV_DIR"

# Install Python dependencies
echo
echo "Installing Python dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

# Make the script executable
chmod +x "$SCRIPT_DIR/dictation.py"

# Create launcher script
cat > "$SCRIPT_DIR/dictate" << 'EOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/dictation.py" "$@"
EOF
chmod +x "$SCRIPT_DIR/dictate"

echo
echo "=== Setup Complete! ==="
echo
echo "IMPORTANT: You need to log out and log back in for the 'input' group to take effect."
echo
echo "Usage:"
echo "  $SCRIPT_DIR/dictate                    # Start with defaults"
echo "  $SCRIPT_DIR/dictate --hotkey KEY_F9    # Use F9 as hotkey"
echo "  $SCRIPT_DIR/dictate --model small      # Use more accurate model"
echo "  $SCRIPT_DIR/dictate --list-keys        # List available hotkeys"
echo
echo "To run as a background service, see: $SCRIPT_DIR/README.md"
