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
            pty INTEGER,
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
            ('mqtt_topic_prefix', 'rds')
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
        frequency = data.get('frequency', 0.0) # Might need to be passed in from scanner state if not in redsea json
        pi = data.get('pi', '')
        ps = data.get('ps', '')
        rt = data.get('rt', '')
        pty = data.get('pty', 0)
        
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
