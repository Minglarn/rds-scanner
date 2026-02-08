import sqlite3
import json
import logging
from datetime import datetime

DB_PATH = '/app/data/rds.db'

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            frequency REAL,
            pi TEXT,
            ps TEXT,
            rt TEXT,
            pty TEXT, -- Changed to TEXT to store "Talk", "Pop Music" etc directly
            tmc INTEGER,
            ta INTEGER,
            tp INTEGER,
            raw_json TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # Initialize default settings if empty
    cursor.execute('SELECT count(*) FROM settings')
    if cursor.fetchone()[0] == 0:
        defaults = [
            ('start_frequency', '88.5'),
            ('start_gain', 'auto'),
            ('scan_step', '0.1'),
            ('scan_integration', '0.2'),
            ('mqtt_broker', 'mosquitto'),
            ('mqtt_port', '1883'),
            ('mqtt_user', ''),
            ('mqtt_password', ''),
            ('mqtt_topic_prefix', 'rds'),
            ('device_index', '0')
        ]
        cursor.executemany('INSERT INTO settings (key, value) VALUES (?, ?)', defaults)
        
    conn.commit()
    conn.close()
    logging.info("Database initialized.")

def get_settings():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT key, value FROM settings')
    rows = cursor.fetchall()
    conn.close()
    return {row['key']: row['value'] for row in rows}

def update_setting(key, value):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, str(value)))
    conn.commit()
    conn.close()

def save_message(data):
    """
    Save a decoded RDS message to the database.
    data: dict containing RDS fields
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Extract fields with defaults
        frequency = data.get('frequency', 0.0)
        pi = data.get('pi', '')
        pi = data.get('pi', '')
        ps = data.get('ps', '')
        # Map radiotext (redsea standard) or rt to rt column
        rt = data.get('radiotext', data.get('rt', ''))
        # Map prog_type (from redsea) to pty column
        pty = data.get('prog_type', '')
        if not pty:
            pty = str(data.get('pty', '')) # Fallback if pty int is provided
        
        # Flags
        tmc = 1 if data.get('tmc') else 0
        ta = 1 if data.get('ta') else 0
        tp = 1 if data.get('tp') else 0
        
        raw_json = json.dumps(data)
        
        cursor.execute('''
            INSERT INTO messages (timestamp, frequency, pi, ps, rt, pty, tmc, ta, tp, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (datetime.utcnow(), frequency, pi, ps, rt, pty, tmc, ta, tp, raw_json))
        
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Error saving message to DB: {e}")

def get_recent_messages(limit=50):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM messages ORDER BY timestamp DESC LIMIT ?', (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_grouped_stations(limit=15):
    """
    Get unique stations (Freq + PI) with aggregated metadata and hit counts.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    # We want the latest PS, RT, PTY for each Frequency + PI
    # And we want to sum the flags and count total hits
    cursor.execute('''
        SELECT 
            frequency, 
            pi, 
            MAX(timestamp) as last_seen,
            (SELECT ps FROM messages m2 WHERE m2.frequency = m1.frequency AND m2.pi = m1.pi AND m2.ps != '' ORDER BY m2.timestamp DESC LIMIT 1) as ps,
            (SELECT rt FROM messages m3 WHERE m3.frequency = m1.frequency AND m3.pi = m1.pi AND m3.rt != '' ORDER BY m3.timestamp DESC LIMIT 1) as rt,
            (SELECT pty FROM messages m4 WHERE m4.frequency = m1.frequency AND m4.pi = m1.pi AND m4.pty != 0 ORDER BY m4.timestamp DESC LIMIT 1) as pty,
            MAX(tmc) as tmc,
            MAX(ta) as ta,
            MAX(tp) as tp,
            COUNT(*) as hit_count
        FROM messages m1
        GROUP BY frequency, pi
        ORDER BY last_seen DESC
        LIMIT ?
    ''', (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def register_signal_peaks(frequencies):
    """
    Inserts placeholder records for detected frequencies so they appear in the UI immediately.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        timestamp = datetime.utcnow()
        
        for freq in frequencies:
            # Always insert a new record for this frequency so it appears as "Recently Found"
            # We use empty PI/PS to indicate it's a raw signal detection
            cursor.execute('''
                INSERT INTO messages (timestamp, frequency, pi, ps, rt, pty, tmc, ta, tp, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (timestamp, freq, '', '', '', '', 0, 0, 0, '{}'))
                
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Error registering peaks: {e}")

def clear_all_messages():
    """Delete all messages from the database."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM messages')
        conn.commit()
        conn.close()
        logging.info("All messages cleared from database.")
    except Exception as e:
        logging.error(f"Error clearing messages: {e}")
