#!/bin/bash
# Raspberry Pi AI Companion — Setup Script (Web-based)
set -e

echo "=== Raspberry Pi AI Companion Setup ==="
echo ""

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[COMPANION]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err() { echo -e "${RED}[ERROR]${NC} $1"; }

# --- 1. System Setup ---
log "Updating system packages..."
sudo apt update
sudo apt upgrade -y

# Install system dependencies
log "Installing system dependencies..."
sudo apt install -y \
    build-essential \
    cmake \
    git \
    pkg-config \
    libasound2-dev \
    portaudio19-dev \
    libsndfile1-dev \
    libturbojpeg0-dev \
    libjpeg-dev \
    libopenjp2-7-dev \
    alsa-utils \
    bluez \
    blueman \
    pipewire \
    pipewire-pulse \
    pipewire-alsa \
    libpipewire-0.3-dev \
    python3 python3-pip python3-venv \
    chromium-browser \
    libffi-dev libssl-dev

# --- 2. Python Virtual Environment ---
log "Setting up Python virtual environment..."
cd ~
mkdir -p ai-companion
cd ai-companion
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip

log "Installing Python dependencies..."
pip install -r requirements.txt

# --- 3. Build whisper.cpp ---
log "Building whisper.cpp..."
cd ~
if [ ! -d whisper.cpp ]; then
    git clone https://github.com/ggml-org/whisper.cpp.git
fi
cd whisper.cpp
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -DWHISPER_PORTAUDIO=ON
make -j$(nproc)
cp bin/whisper-cli ~/ai-companion/whisper-cli
log "whisper.cpp built successfully!"

# --- 4. Install Piper TTS ---
log "Installing Piper TTS..."
cd ~
# Check architecture
ARCH=$(dpkg --print-architecture)
log "Architecture: $ARCH"

if [ "$ARCH" = "armhf" ]; then
    wget -q https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_armv7l.tar.gz
    tar xzf piper_linux_armv7l.tar.gz
elif [ "$ARCH" = "arm64" ]; then
    wget -q https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz
    tar xzf piper_linux_aarch64.tar.gz
else
    err "Unsupported architecture: $ARCH"
    exit 1
fi

sudo cp piper/bin/piper /usr/local/bin/piper
sudo chmod +x /usr/local/bin/piper

# Download voice model
mkdir -p ~/.local/share/piper/voices
cd ~/.local/share/piper/voices
if [ ! -f en_US-amy-low.onnx ]; then
    wget -q https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/low/en_US-amy-low.onnx
    wget -q https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/low/en_US-amy-low.onnx.json
fi
log "Piper TTS installed!"

# --- 5. Set up companion code ---
log "Setting up companion code..."
cd ~/ai-companion
source venv/bin/activate
pip install -r requirements.txt

# Create log directory
mkdir -p logs

# --- 6. Verify everything ---
log ""
log "=== Verification ==="
echo ""
echo "whisper.cpp: $(~/ai-companion/whisper-cli --help 2>&1 | head -1 || echo 'BUILD FAILED')"
echo "Piper: $(piper --help 2>&1 | head -1 || echo 'INSTALL FAILED')"
python3 -c "import flask; print(f'Flask: {flask.__version__}')" || echo "Flask: INSTALL FAILED"
python3 -c "import sounddevice; print(f'sounddevice: OK')" || echo "sounddevice: INSTALL FAILED"
python3 -c "import onnxruntime; print(f'onnxruntime: {onnxruntime.__version__}')" || echo "onnxruntime: INSTALL FAILED"
echo ""

# --- 7. Start PipeWire (required for audio) ---
log "Ensuring PipeWire audio is running..."
systemctl --user daemon-reload 2>/dev/null
systemctl --user start pipewire pipewire-pulse wireplumber 2>/dev/null
systemctl --user enable pipewire pipewire-pulse wireplumber 2>/dev/null
sleep 1
echo ""
log "PipeWire status: $(systemctl --user is-active pipewire-pulse 2>/dev/null || echo 'unknown')"

# --- 8. Instructions ---
log ""
log "=== Setup Complete ==="
log ""
log "Next steps:"
log ""
log "1. Edit ~/ai-companion/config.yaml:"
log "   - hermes_api_key: YOUR_KEY"
log "   - ha url and token"
log ""
log "2. Pair Bluetooth speaker:"
log "   sudo bluetoothctl"
log "   power on"
log "   scan on"
log "   pair <MAC>"
log "   trust <MAC>"
log "   connect <MAC>"
log ""
log "3. Start the web server (in one terminal):"
log "   cd ~/ai-companion && source venv/bin/activate"
log "   python3 web/server.py"
log ""
log "4. Open Chromium in kiosk mode (in another terminal):"
log "   chromium-browser --kiosk --no-first-run --disable-features=TranslateUI http://localhost:5000"
log ""
log "5. Start the orchestrator (in another terminal):"
log "   cd ~/ai-companion && source venv/bin/activate"
log "   python3 orchestrator.py"
log ""
log "Or use the launch script:"
log "   bash scripts/launch.sh"
log ""
