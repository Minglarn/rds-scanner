from flask import Flask, render_template, request, jsonify, redirect, url_for, Response, make_response
import logging
import threading
import time
from app.scanner import scanner_instance
from app.database import init_db, get_recent_messages, get_grouped_stations, get_db_connection, get_settings, update_setting, clear_all_messages
from app.mqtt_client import init_mqtt
from app.audio_stream import get_audio_stream, audio_streamer
from app.dab_scanner import dab_scanner, DAB_CHANNELS

# Current radio mode: 'fm' or 'dab'
current_mode = 'fm'

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def force_release_usb():
    """Nuclear option: kill all potentially device-holding processes."""
    import subprocess
    logging.info("Running USB release (killing all radio processes)...")
    processes = ['rtl_fm', 'redsea', 'welle-cli', 'rtl_power', 'airspy_rx']
    
    # First try graceful stop
    for p in processes:
        try:
            subprocess.run(['pkill', p], stderr=subprocess.DEVNULL, timeout=1)
        except:
            pass
    
    time.sleep(0.5)
    
    # Then force kill
    for p in processes:
        try:
            subprocess.run(['pkill', '-9', p], stderr=subprocess.DEVNULL, timeout=1)
        except:
            pass
    
    time.sleep(0.5)
    
    # Verify rtl_fm is dead (the most common offender)
    try:
        result = subprocess.run(['pgrep', '-c', 'rtl_fm'], capture_output=True, timeout=1)
        count = result.stdout.decode().strip()
        if count and count != '0':
            logging.warning(f"rtl_fm processes still running after force kill: {count}")
        else:
            logging.debug("All radio processes confirmed killed")
    except:
        pass
    
    time.sleep(0.5)  # Final settle time

# Filter out noisy polling requests from logs
class EndpointFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return msg.find('/partials/messages') == -1 and \
               msg.find('/api/dab/status') == -1 and \
               msg.find('/api/status') == -1

logging.getLogger("werkzeug").addFilter(EndpointFilter())

PTY_NAMES = {
    0: "None", 1: "News", 2: "Current Affairs", 3: "Information", 4: "Sport",
    5: "Education", 6: "Drama", 7: "Culture", 8: "Science", 9: "Varied",
    10: "Pop Music", 11: "Rock Music", 12: "Easy Listening", 13: "Light Classical",
    14: "Serious Classical", 15: "Other Music", 16: "Weather", 17: "Finance",
    18: "Children's", 19: "Social Affairs", 20: "Religion", 21: "Phone In",
    22: "Travel", 23: "Leisure", 24: "Jazz", 25: "Country", 26: "National Music",
    27: "Oldies", 28: "Folk", 29: "Documentary", 30: "Alarm Test", 31: "Alarm"
}

app = Flask(__name__)

@app.template_filter('pty_name')
def pty_name_filter(code):
    try:
        return PTY_NAMES.get(int(code), f"Type {code}")
    except:
        return f"Type {code}"

# Initialize components
init_db()
init_mqtt()

# Start scanner in 2 seconds to allow Flask to start
def start_scanner_delayed():
    time.sleep(2)
    scanner_instance.start()

threading.Thread(target=start_scanner_delayed, daemon=True).start()

@app.route('/')
def index():
    """Render the main page."""
    response = make_response(render_template('index.html'))
    # Aggressively disable caching to ensure UI updates appear immediately
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/api/status', methods=['GET'])
def get_status():
    # Get current station RDS info if available
    current_rds = None
    stations = get_grouped_stations(50)
    for s in stations:
        if abs(float(s.get('frequency', 0)) - scanner_instance.current_frequency) < 0.05:
            current_rds = s
            break
    
    return jsonify({
        'frequency': scanner_instance.current_frequency,
        'gain': scanner_instance.current_gain,
        'running': scanner_instance.running,
        'searching': scanner_instance.searching,
        'current_station': current_rds,
        'scan_status': scanner_instance.scan_status,
        'scan_progress': scanner_instance.scan_progress,
        'scan_total': scanner_instance.scan_total,
        'stations_found': scanner_instance.stations_found
    })

@app.route('/api/tune', methods=['POST'])
def tune():
    data = request.json
    try:
        freq = float(data.get('frequency', scanner_instance.current_frequency))
        # If it's a DAB frequency, don't let FM try to tune it
        if freq > 108.0:
            logging.info(f"Ignoring FM tune request for DAB frequency {freq} MHz")
            return jsonify({'error': 'DAB frequency', 'redirect': 'dab'}), 400
            
        gain = data.get('gain', scanner_instance.current_gain)
        # Manual tune stops auto-search
        scanner_instance.searching = False
        scanner_instance.tune(freq, gain)
        return jsonify({'status': 'ok', 'frequency': freq, 'gain': gain})
    except ValueError:
        return jsonify({'error': 'Invalid frequency or gain'}), 400

@app.route('/api/scan/next', methods=['POST'])
def scan_next():
    try:
        scanner_instance.start_auto_search()
        return jsonify({'status': 'searching'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/messages', methods=['GET'])
def messages():
    limit = int(request.args.get('limit', 50))
    sort_by = request.args.get('sort', 'frequency')
    msgs = get_grouped_stations(limit, sort_by)
    return jsonify(msgs)

@app.route('/settings')
def settings_page():
    settings = get_settings()
    return render_template('settings.html', settings=settings)

@app.route('/api/settings', methods=['POST'])
def save_settings_route():
    try:
        data = request.form
        for key, value in data.items():
            update_setting(key, value)
            
        # Reload MQTT configuration
        init_mqtt()
        
        return redirect(url_for('settings_page'))
    except Exception as e:
        logging.error(f"Error saving settings: {e}")
        return f"Error saving settings: {e}", 500

@app.route('/partials/messages')
def messages_partial():
    # Return HTML fragment for HTMX
    limit = int(request.args.get('limit', 50))
    sort_by = request.args.get('sort', 'frequency')
    stations = get_grouped_stations(limit, sort_by)
    return render_template('messages_list.html', stations=stations)

@app.route('/api/messages/clear', methods=['POST'])
def clear_messages():
    clear_all_messages()
    # Also clear peak cache so next scan is fresh
    scanner_instance.peak_cache = []
    return jsonify({'status': 'cleared'})

@app.route('/api/audio/stream')
def audio_stream():
    """Stream live FM audio for the current frequency."""
    freq = request.args.get('freq', scanner_instance.current_frequency)
    freq = request.args.get('freq', 88.5)
    gain = request.args.get('gain', scanner_instance.current_gain)
    
    # Stop the background scanner to release the device
    if scanner_instance.running:
        scanner_instance.stop()
        time.sleep(1) # Give it a moment to release device
        
    return get_audio_stream(float(freq), gain)

@app.route('/api/audio/stop', methods=['POST'])
def audio_stop():
    """Stop the audio stream."""
    """Stop the audio stream."""
    audio_streamer.stop()
    
    # Restart the background scanner if we are in FM mode and DAB isn't active
    if current_mode == 'fm' and not scanner_instance.running and not dab_scanner.running:
        time.sleep(1) # Wait for audio process to die
        scanner_instance.start()
        
    return jsonify({'status': 'stopped'})

# ========== DAB ROUTES ==========

@app.route('/api/mode', methods=['GET'])
def get_mode():
    """Get current radio mode (fm or dab)."""
    global current_mode
    return jsonify({'mode': current_mode})

@app.route('/api/mode', methods=['POST'])
def set_mode():
    """Switch between FM and DAB mode."""
    global current_mode
    data = request.json
    new_mode = data.get('mode', 'fm').lower()
    
    if new_mode not in ['fm', 'dab']:
        return jsonify({'error': 'Invalid mode. Use fm or dab'}), 400
    
    if new_mode == current_mode:
        return jsonify({'mode': current_mode, 'message': 'Already in this mode'})
        
    logging.info(f"Switching mode to: {new_mode}")
    current_mode = new_mode  # Update globally as early as possible
    
    # Switch modes - only one can use RTL-SDR at a time
    if new_mode == 'dab':
        # Disable audio streaming to prevent restart during transition
        audio_streamer.disable()
        scanner_instance.stop()
        force_release_usb()
        logging.info("Allowing USB device to settle (2.0s) before starting DAB...")
        time.sleep(2.0)
        dab_scanner.start()
    else:
        dab_scanner.stop()
        force_release_usb()
        logging.info("Allowing USB device to settle (1.5s) before starting FM...")
        time.sleep(1.5)
        # Re-enable audio streaming for FM mode
        audio_streamer.enable()
        scanner_instance.start()
    
    return jsonify({'mode': current_mode, 'message': f'Switched to {new_mode.upper()} mode'})

@app.route('/api/dab/status', methods=['GET'])
def dab_status():
    """Get DAB receiver status."""
    return jsonify(dab_scanner.get_status())

@app.route('/api/dab/channels', methods=['GET'])
def dab_channels():
    """Get list of available DAB channels."""
    return jsonify({'channels': list(DAB_CHANNELS.keys())})

@app.route('/api/dab/tune', methods=['POST'])
def dab_tune():
    """Tune to a DAB channel or service."""
    data = request.json
    channel = data.get('channel')
    freq = data.get('frequency')
    service = data.get('service')
    gain = data.get('gain')
    
    # Resolve frequency to channel label if needed
    if freq and not channel:
        channel = dab_scanner.find_channel_by_freq(freq)
        logging.info(f"Resolved frequency {freq} MHz to DAB channel {channel}")

    if channel:
        success = dab_scanner.tune_channel(channel)
        if success:
            # If service is also provided, tune to it after mux is initialized
            if service:
                time.sleep(1.5)
                dab_scanner.tune_service(service)
            return jsonify({'status': 'ok', 'channel': channel, 'service': service})
        else:
            return jsonify({'error': f'Failed to tune to {channel}'}), 500
            
    if gain is not None:
        success = dab_scanner.set_gain(gain)
        if success:
            return jsonify({'status': 'ok', 'gain': gain})
        else:
            return jsonify({'error': 'Failed to set gain'}), 500
    
    if service:
        success = dab_scanner.tune_service(service)
        if success:
            return jsonify({'status': 'ok', 'service': service})
        else:
            return jsonify({'error': f'Failed to tune to service {service}'}), 500
    
    return jsonify({'error': 'Specify channel, frequency, service, or gain'}), 400

@app.route('/api/dab/audio')
def dab_audio():
    """Proxy DAB audio stream from welle-cli."""
    import requests as req
    
    if not dab_scanner.running:
        return jsonify({'error': 'DAB not running'}), 400
    
    def generate():
        try:
            # Stream from welle-cli's internal web server
            with req.get(f'http://localhost:{dab_scanner.web_port}/mp3', stream=True, timeout=30) as r:
                logging.info(f"DAB audio from welle-cli: status={r.status_code}, content-type={r.headers.get('Content-Type')}")
                if not r.ok:
                    logging.error(f"DAB audio stream failed: {r.status_code}")
                    return
                for chunk in r.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
        except Exception as e:
            logging.error(f"DAB audio proxy error: {e}")
    
    return Response(generate(), mimetype='audio/mpeg', headers={
        'Cache-Control': 'no-cache, no-store',
        'Connection': 'keep-alive',
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False) # Debug mode False for production use
