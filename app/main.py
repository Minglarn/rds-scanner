from flask import Flask, render_template, request, jsonify, redirect, url_for
import logging
import threading
import time
from app.scanner import scanner_instance
from app.database import init_db, get_recent_messages, get_db_connection, get_settings, update_setting
from app.mqtt_client import init_mqtt

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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
    return render_template('index.html')

@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify({
        'frequency': scanner_instance.current_frequency,
        'gain': scanner_instance.current_gain,
        'running': scanner_instance.running,
        'searching': scanner_instance.searching
    })

@app.route('/api/tune', methods=['POST'])
def tune():
    data = request.json
    try:
        freq = float(data.get('frequency', scanner_instance.current_frequency))
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
    msgs = get_recent_messages(limit)
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
    limit = int(request.args.get('limit', 20))
    messages = get_recent_messages(limit)
    return render_template('messages_list.html', messages=messages)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False) # Debug mode False for production use
