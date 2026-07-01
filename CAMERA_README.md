# Raspberry Pi AI Companion — Camera Setup Reference

**Last Updated:** June 22, 2026  
**Status:** Ready for camera installation  
**Hardware:** Raspberry Pi 5 (16GB RAM) + Pi Camera Module (pending order)

---

## Current Configuration (Ready)

### 1. Config.yaml (Updated & Verified)
Path: `/home/daveealex/ai-companion/config.yaml`

**LLM Backend:**
```yaml
llm:
  provider: "hermes"
  hermes_api_url: "http://192.168.1.109:8642/v1"
  hermes_api_key: "97b68c4579a3b96142225bd3f76c3ea66d06f5ed77cf6dd2"
  hermes_model: "Qwen3.6-35B-A3B-MTP-GGUF-UD-Q4_K_XL"
```

**Camera Section (Enabled when ready):**
```yaml
camera:
  enabled: false                # Set to true when camera is physically installed
  type: "picamera"              # Options: picamera, usb
  resolution: "1280x720"
  stream_url: "http://localhost:5000/cam/stream"
  snapshot_url: "http://localhost:5000/cam/snapshot"
  capture_format: "jpeg"
  vision_prompt: "Describe what you see in this image in one short sentence."
```

### 2. LLM Client (Updated & Verified)
Path: `/home/daveealex/ai-companion/llm/client.py`

**VLM Support Added:**
- `chat(user_message, image_url=None)` — accepts optional image URL
- Multimodal message formatting (OpenAI `image_url` format)
- Backward compatible — text-only chat works unchanged

---

## Memory Setup (Honcho — Standalone)

**On Main Machine (Hermes Host):**
```bash
hermes config set memory.provider honcho
hermes config set memory.memory_enabled true
hermes config set memory.user_profile_enabled true
hermes gateway restart
```

Honcho creates a local SQLite database (`~/.hermes/honcho.db`) for persistent memory. No external servers, no API keys.

---

## Model Choices for Vision

### Option A: Local on Pi (Recommended)
- **Model:** `Qwen2.5-VL-3B-Instruct` (Q4_K_M GGUF)
- **Speed:** ~15-20 TPS on Pi 5
- **RAM:** ~2GB
- **Pros:** Fast, offline, instant
- **Cons:** Basic reasoning, limited context

### Option B: Offload to Main Machine
- **Model:** `Qwen2.5-VL-7B-Instruct` (Q4_K_M GGUF)
- **Speed:** ~5-10 TPS via LAN
- **RAM:** ~5GB on main machine
- **Pros:** Better reasoning, larger context
- **Cons:** Network latency, requires Hermes gateway running

### Current Daily Driver (Text)
- `Qwen3.6-35B-A3B-MTP-GGUF-UD-Q4_K_XL` via Hermes API
- Runs on Strix Halo (192.168.1.137) or local
- Excellent reasoning, tool use, instruction following

---

## Network Details

**Main Machine (Hermes Gateway):**
- IP: `192.168.1.109` (Pop!_OS)
- API Server: Port 8642
- Status: Running (`ss -tlnp | grep 8642` shows LISTEN)

**Strix Halo (Backup):**
- IP: `192.168.1.137`
- Port: 13305
- Model: `Qwen3.6-35B-A3B-MTP-GGUF`

**Pi 5 (Companion):**
- IP: `192.168.1.184`
- User: `daveealex`
- Password: `Spinhardalex@1`
- OS: Debian 13 (testing)

---

## When Camera Arrives: Setup Steps

### 1. Install Camera
```bash
# Enable camera interface (if using picamera)
sudo raspi-config
# Interface Options → Camera → Yes

# Test camera
libcamera-hello --width 1280 --height 720
```

### 2. Update config.yaml
```yaml
camera:
  enabled: true
  type: "picamera"  # or "usb" if using USB cam
  resolution: "1280x720"
```

### 3. Update Web Server (server.py)
Add camera stream endpoint:
```python
from flask import Response

def generate_frames():
    while True:
        frame = capture_frame()  # From camera
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/cam/stream')
def cam_stream():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/cam/snapshot')
def cam_snapshot():
    return capture_frame()  # Return single JPEG
```

### 4. Update LLM Client (client.py)
Already ready — just pass image URL:
```python
response = await client.chat("What do you see?", image_url="http://localhost:5000/cam/snapshot")
```

### 5. Test VLM Integration
```bash
# Test image URL accessibility
curl -I http://localhost:5000/cam/snapshot

# Test VLM response
curl http://192.168.1.109:8642/v1/chat/completions \
  -H "Authorization: Bearer 97b68c4579a3b96142225bd3f76c3ea66d06f5ed77cf6dd2" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hermes-agent",
    "messages": [
      {"role": "system", "content": "You are a helpful AI companion."},
      {"role": "user", "content": [
        {"type": "text", "text": "What is in this image?"},
        {"type": "image_url", "image_url": {"url": "http://192.168.1.184:5000/cam/snapshot"}}
      ]}
    ]
  }'
```

---

## Pending Items

- [ ] Camera module ordered
- [ ] Camera physically installed and tested
- [ ] Web server updated with camera stream endpoints
- [ ] VLM model downloaded (Qwen2.5-VL-3B or 7B)
- [ ] Integration tested with live camera feed
- [ ] Honcho memory verified (running on main machine)

---

## Key Files

- Config: `/home/daveealex/ai-companion/config.yaml`
- LLM Client: `/home/daveealex/ai-companion/llm/client.py`
- Hermes Config: `/home/daveealex/.hermes/config.yaml`
- Honcho DB: `~/.hermes/honcho.db` (created automatically)

---

## Notes

- Camera support is **non-breaking** — current text chat works without camera
- Honcho memory runs on main machine, Pi connects via API
- VLM models are ~2-5GB, fit easily on Pi 5 (16GB)
- Use `jpeg` format for snapshots (smaller/faster than png)
- Streaming MJPEG works in browsers (face display)
