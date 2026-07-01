#!/usr/bin/env python3
"""
Flask Web Server — Serves the companion's face and content.

Endpoints:
  GET  /              — Main face page (kiosk mode)
  GET  /stream        — Server-Sent Events for real-time face updates
  POST /api/state     — Set face state (from orchestrator)
  POST /api/content   — Inject HTML content
  POST /api/speak     — Start/stop speaking (for waveform)
  GET  /api/status    — Get current state (for polling fallback)

The orchestrator calls POST /api/* endpoints to control the face.
The browser connects to GET /stream for real-time updates.

Usage:
    python3 web/server.py

Then open Chromium in kiosk mode:
    chromium-browser --kiosk http://localhost:5000
"""

import asyncio
import json
import os
import time
import logging
from datetime import datetime
from flask import Flask, render_template, jsonify, Response, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

logger = logging.getLogger(__name__)

# ─── State ───
face_state = {
    'current': 'idle',
    'target': 'idle',
    'isSpeaking': False,
    'isListening': False,
    'lastUpdate': None,
}

# Event listeners (for SSE)
_event_listeners = []

# ─── SSE Stream ───
def event_stream():
    """SSE generator for real-time face updates."""
    listener = {'queue': []}
    _event_listeners.append(listener)
    
    try:
        while True:
            # Flush queued events
            while listener['queue']:
                event = listener['queue'].pop(0)
                yield f"event: state\n\ndata: {json.dumps(event)}\n\n"
            
            # Check for state changes
            if face_state.get('lastUpdate') and face_state.get('lastUpdate') != listener.get('lastSent'):
                event = {
                    'state': face_state['target'],
                    'content': face_state.get('pendingContent'),
                    'append': face_state.get('pendingAppend'),
                    'timestamp': face_state['lastUpdate'],
                }
                listener['lastSent'] = face_state['lastUpdate']
                yield f"event: state\n\ndata: {json.dumps(event)}\n\n"
            
            time.sleep(0.1)
    except GeneratorExit:
        pass

def broadcast(event_data):
    """Broadcast an event to all SSE listeners."""
    face_state['lastUpdate'] = datetime.now().isoformat()
    for listener in _event_listeners:
        listener['queue'].append(event_data)

# ─── Routes ───
@app.route('/')
def index():
    """Main page."""
    return render_template('index.html')

@app.route('/stream')
def stream():
    """SSE stream for real-time updates."""
    return Response(event_stream(), mimetype='text/event-stream')

@app.route('/api/state', methods=['POST'])
def set_state():
    """Set face state."""
    data = request.json
    new_state = data.get('state', 'idle')
    
    valid_states = ['idle', 'listening', 'thinking', 'speaking', 'happy', 'confused']
    if new_state not in valid_states:
        return jsonify({'error': f'Invalid state. Must be one of {valid_states}'}), 400
    
    face_state['target'] = new_state
    face_state['current'] = new_state
    
    broadcast({'state': new_state})
    logger.info(f"Face state → {new_state}")
    
    return jsonify({'state': new_state, 'timestamp': face_state['lastUpdate']})

@app.route('/api/content', methods=['POST'])
def set_content():
    """Inject HTML content (replaces current content)."""
    data = request.json
    content = data.get('content', '')
    
    face_state['pendingContent'] = content
    face_state['pendingAppend'] = None
    
    broadcast({
        'content': content,
        'append': None,
        'state': face_state['target'],
    })
    
    logger.info(f"Content injected ({len(content)} chars)")
    return jsonify({'status': 'ok', 'length': len(content)})

@app.route('/api/content/append', methods=['POST'])
def append_content():
    """Append HTML content."""
    data = request.json
    content = data.get('content', '')
    
    face_state['pendingContent'] = None
    face_state['pendingAppend'] = content
    
    broadcast({
        'append': content,
        'content': None,
        'state': face_state['target'],
    })
    
    logger.info(f"Content appended ({len(content)} chars)")
    return jsonify({'status': 'ok', 'length': len(content)})

@app.route('/api/speak', methods=['POST'])
def set_speaking():
    """Set speaking state (triggers waveform animation)."""
    data = request.json
    speaking = data.get('speaking', False)
    amplitude = data.get('amplitude', 0)  # 0-1
    
    face_state['isSpeaking'] = speaking
    face_state['pendingContent'] = None
    face_state['pendingAppend'] = None
    
    if speaking:
        # Set to speaking state if not already
        if face_state['target'] not in ('speaking',):
            face_state['target'] = 'speaking'
            face_state['current'] = 'speaking'
    
    broadcast({
        'state': face_state['target'],
        'content': None,
        'append': None,
    })
    
    logger.info(f"Speaking → {speaking} (amp: {amplitude})")
    return jsonify({'speaking': speaking})

@app.route('/api/status', methods=['GET'])
def get_status():
    """Get current state (for polling fallback)."""
    return jsonify({
        'state': face_state['target'],
        'isSpeaking': face_state['isSpeaking'],
        'isListening': face_state['isListening'],
        'lastUpdate': face_state['lastUpdate'],
    })

@app.route('/api/reset', methods=['POST'])
def reset_face():
    """Reset face to idle."""
    face_state['target'] = 'idle'
    face_state['current'] = 'idle'
    face_state['pendingContent'] = None
    face_state['pendingAppend'] = None
    face_state['isSpeaking'] = False
    
    broadcast({'state': 'idle'})
    return jsonify({'state': 'idle'})

@app.route('/api/clear-context', methods=['POST'])
def clear_context():
    """Clear LLM conversation context by calling the orchestrator."""
    orchestrator_host = os.environ.get('ORCHESTRATOR_HOST', 'http://127.0.0.1:9999')
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{orchestrator_host}/api/clear-context",
            data=b"",
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read())
            # Show confirmation on face
            face_state['pendingContent'] = (
                '<p style="text-align: center; color: #4ade80; font-size: 18px;">✓ Conversation cleared</p>'
            )
            broadcast({'state': 'idle', 'content': face_state['pendingContent']})
            return jsonify(result)
    except Exception as e:
        logger.error(f"Failed to clear context: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/context-stats', methods=['GET'])
def context_stats():
    """Get LLM conversation statistics from the orchestrator."""
    orchestrator_host = os.environ.get('ORCHESTRATOR_HOST', 'http://127.0.0.1:9999')
    try:
        import urllib.request
        with urllib.request.urlopen(f"{orchestrator_host}/api/context-stats", timeout=5) as resp:
            return jsonify(json.loads(resp.read()))
    except Exception as e:
        # Gracefully return defaults if orchestrator isn't available
        return jsonify({
            'turns': 0,
            'tokens_used': 0,
            'context_window': 0,
            'available': False
        })


@app.route('/api/inference-settings', methods=['GET', 'POST'])
def inference_settings():
    """Get or update inference server settings."""
    import yaml as yaml_mod
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.yaml')

    if request.method == 'GET':
        try:
            with open(config_path, 'r') as f:
                config = yaml_mod.safe_load(f)
            llm_config = config.get('llm', {})
            return jsonify({
                "provider": llm_config.get("provider", "hermes"),
                "external_url": llm_config.get("external_url", ""),
                "external_model": llm_config.get("external_model", ""),
                "hermes_api_url": llm_config.get("hermes_api_url", ""),
                "hermes_model": llm_config.get("hermes_model", ""),
            })
        except Exception as e:
            logger.error(f"Failed to read inference settings: {e}")
            return jsonify({"error": str(e)}), 500

    elif request.method == 'POST':
        data = request.get_json()
        try:
            with open(config_path, 'r') as f:
                config = yaml_mod.safe_load(f)
            if 'llm' not in config:
                config['llm'] = {}
            config['llm']['provider'] = data.get('provider', config['llm'].get('provider', 'hermes'))
            config['llm']['external_url'] = data.get('external_url', config['llm'].get('external_url', ''))
            config['llm']['external_model'] = data.get('external_model', config['llm'].get('external_model', ''))
            with open(config_path, 'w') as f:
                yaml_mod.dump(config, f, default_flow_style=False, sort_keys=False)
            logger.info(f"Inference settings updated: provider={config['llm']['provider']}")
            return jsonify({
                "status": "ok",
                "provider": config['llm']['provider'],
                "external_url": config['llm']['external_url'],
            })
        except Exception as e:
            logger.error(f"Failed to save inference settings: {e}")
            return jsonify({"error": str(e)}), 500

@app.route('/api/face-image', methods=['POST'])
def face_image():
    """Receive a base64-encoded face image (for camera integration)."""
    data = request.json
    image_data = data.get('image')
    # In future: save and display image
    logger.info(f"Face image received ({len(image_data)} chars)")
    return jsonify({'status': 'ok'})

# ─── Main ───
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    print("\n" + "="*60)
    print("  Atlas Companion — Web Server")
    print("="*60)
    print(f"  Face page: http://localhost:5001")
    print(f"  API:       http://localhost:5001/api/state (POST)")
    print(f"  API:       http://localhost:5001/api/content (POST)")
    print(f"  API:       http://localhost:5001/api/speak (POST)")
    print("="*60)
    print("\nKiosk mode:")
    print("  chromium-browser --kiosk --no-first-run http://localhost:5000")
    print("\n")
    
    app.run(host='0.0.0.0', port=5000, threaded=True)
