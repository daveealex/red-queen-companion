# Atlas — AI Companion on Raspberry Pi 5

A voice-driven AI companion with an animated face (eyes + mouth) on a Raspberry Pi 5.
Powered by **Hermes** (cloud LLM), **Piper** (local TTS), and **whisper.cpp** (local STT).
Web-based face display using Flask + Chromium kiosk.

## Architecture

```
  ┌───────────┐    ┌───────────┐    ┌──────────┐
  │ Monitor    │    │ BT Speaker│    │  Hermes  │
  │ (Eyes+Mouth)│   │ (In+Out)  │    │  (Cloud  │
  └─────┬──────┘    └─────┬─────┘    │  LLM)    │
        │                 │           └────┬─────┘
  ┌─────▼─────────────────▼───────────────┐
  │           RASPBERRY PI 5 (16GB)       │
  │                                       │
  │  Chromium Kiosk ◄── Flask Server ──►  │
  │  (SVG face + HTML content)   Orchestrator ─► Hermes API   │
  │  Piper TTS  ──►                        │
  │  whisper.cpp◄── VAD                    │
  │  HA Integration ──► Home Assistant     │
  └───────────────────────────────────────┘
```

## Features

- **Voice-first interaction** — Always-on VAD, just talk to it
- **Web-based animated face** — SVG eyes (blinking, dilation, expressions) + mouth (speech waveform)
- **Rich content display** — Any HTML: images, math (KaTeX), diagrams, SVG, charts
- **Local TTS** — Piper TTS, faster than realtime on Pi 5
- **Local STT** — whisper.cpp, fast and accurate
- **Cloud LLM** — Hermes API for intelligent responses
- **Home Assistant integration** — Control lights, check sensors, execute scripts
- **Spare CPU** — ~40% headroom for sensors (PIR, ultrasonic, etc.)

## Quick Start

### On the Pi 5
```bash
# 1. Flash Raspberry Pi OS Lite 64-bit to 32GB microSD
# 2. Boot the Pi, connect via Ethernet

# 3. Clone and setup:
git clone <repo> ~/ai-companion
cd ~/ai-companion
bash scripts/setup-pi.sh

# 4. Edit config.yaml with your credentials
nano config.yaml

# 5. Launch everything:
bash scripts/launch.sh
```

### Manual Start (3 terminals)
```bash
# Terminal 1 — Web server
cd ~/ai-companion && source venv/bin/activate
python3 web/server.py

# Terminal 2 — Chromium kiosk
chromium-browser --kiosk --no-first-run --disable-features=TranslateUI http://localhost:5000

# Terminal 3 — Orchestrator
cd ~/ai-companion && source venv/bin/activate
python3 orchestrator.py
```

## Configuration

Edit `config.yaml`:

```yaml
llm:
  provider: "hermes"
  hermes_api_key: "YOUR_KEY"
  hermes_model: "qwen3.6-35b-a3b-mtp"

ha:
  url: "http://192.168.1.x:8123"
  token: "YOUR_HA_TOKEN"

web:
  server_url: "http://localhost:5000"
```

## Face States

| State | Visual | When |
|-------|--------|------|
| idle | Gentle breathing, slight smile | Waiting for input |
| listening | Eyes widen, mouth slightly open | VAD detected speech |
| thinking | Eyes dart around, mouth closed | Sending to LLM |
| speaking | Eyes focused, mouth animates | TTS playing |
| happy | Eyes squint, big smile | Positive interaction |
| confused | One eyebrow raises, mouth tilts | Unclear input |

## Voice Commands

### Home Assistant
```
"Turn on the living room light"
"Turn off the bedroom light"
"What's the temperature?"
"Is there any motion?"
```

### General
Just talk naturally — the LLM handles everything else.

## Rich Content

The face page supports ANY HTML content. The LLM can send:

**Images:**
```html
<img src="https://example.com/duck.jpg" alt="A duck">
```

**Math (KaTeX):**
```html
<div class="math-display">$$E = mc^2$$</div>
```

**Diagrams:**
```html
<svg width="200" height="100">...</svg>
```

**Code blocks:**
```html
<pre><code>print("Hello, world!")</code></pre>
```

**Tables, charts, anything.**

## Hardware

- **Raspberry Pi 5** — 16GB RAM
- **HDMI monitor** — For the face display
- **Bluetooth speaker with mic** — Audio I/O
- **32GB microSD** — OS + software
- **Pi Camera Module 3** (future) — Vision capabilities

## Directory Structure

```
ai-companion/
├── orchestrator.py       # Main event loop
├── config.yaml           # Configuration
├── requirements.txt      # Python dependencies
├── assets/
│   └── system_prompt.md  # Companion personality
├── audio/
│   ├── vad_detector.py   # Silero VAD
│   ├── stt.py            # whisper.cpp wrapper
│   └── tts.py            # Piper TTS wrapper
├── llm/
│   └── client.py         # Hermes API client
├── ha/
│   └── integration.py    # Home Assistant API
├── web/
│   ├── server.py         # Flask web server
│   └── templates/
│       └── index.html    # Face + content page
├── scripts/
│   ├── setup-pi.sh       # One-command Pi setup
│   ├── launch.sh         # Start all services
│   └── companion.service # Systemd auto-start
└── logs/                 # Runtime logs
```

## Troubleshooting

**Web server won't start:**
```bash
cd ~/ai-companion && source venv/bin/activate
pip install -r requirements.txt
python3 web/server.py
```

**Chromium won't open in kiosk mode:**
```bash
# Check Chromium is installed
chromium-browser --version
# Try without kiosk first
chromium-browser http://localhost:5000
```

**No audio output:**
```bash
pactl list short sinks          # List sinks
pactl set-default-sink <id>     # Set Bluetooth sink
pavucontrol                     # GUI tool to select output
```

**whisper.cpp not found:**
```bash
cd ~/whisper.cpp && mkdir -p build && cd build
cmake .. && make -j$(nproc)
cp bin/whisper-cli ~/ai-companion/whisper-cli
```

**Piper not working:**
```bash
piper --help
ls ~/.local/share/piper/voices/en/en_US/amy/low/
```
