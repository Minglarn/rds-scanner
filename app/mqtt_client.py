import paho.mqtt.client as mqtt
import json
import logging
from app.database import get_settings

client = None

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logging.info("Connected to MQTT Broker!")
    else:
        logging.error(f"Failed to connect, return code {rc}")

def init_mqtt():
    global client
    settings = get_settings()
    
    broker = settings.get('mqtt_broker', 'mosquitto')
    port = int(settings.get('mqtt_port', 1883))
    user = settings.get('mqtt_user', '')
    password = settings.get('mqtt_password', '')
    
    if not broker:
        logging.warning("MQTT Broker not configured.")
        return

    # cleanup old client if exists
    if client:
        try:
            client.loop_stop()
            client.disconnect()
        except:
            pass

    client = mqtt.Client()
    if user and password:
        client.username_pw_set(user, password)
        
    client.on_connect = on_connect
    
    try:
        logging.info(f"Connecting to MQTT Broker {broker}:{port}...")
        client.connect(broker, port, 60)
        client.loop_start()
    except Exception as e:
        logging.error(f"Could not connect to MQTT Broker: {e}")
        client = None

def publish_rds(data):
    if not client:
        return

    settings = get_settings()
    topic_prefix = settings.get('mqtt_topic_prefix', 'rds')

    try:
        # Publish full JSON
        client.publish(f"{topic_prefix}/json", json.dumps(data))
        
        # Publish specific fields
        if 'ps' in data:
            client.publish(f"{topic_prefix}/ps", data['ps'])
        if 'rt' in data:
            client.publish(f"{topic_prefix}/rt", data['rt'])
        if 'pi' in data:
            client.publish(f"{topic_prefix}/pi", data['pi'])
        if 'pty' in data:
            client.publish(f"{topic_prefix}/pty", str(data['pty']))
        if 'frequency' in data:
            client.publish(f"{topic_prefix}/frequency", str(data['frequency']))
        
        # DAB specific topics
        if data.get('dab'):
            if 'dab_ensemble' in data:
                client.publish(f"{topic_prefix}/dab_ensemble", data['dab_ensemble'])
            if 'dab_tii' in data:
                client.publish(f"{topic_prefix}/dab_tii", data['dab_tii'])
            if 'dab_snr' in data:
                client.publish(f"{topic_prefix}/dab_snr", str(data['dab_snr']))
            
    except Exception as e:
        logging.error(f"Error publishing to MQTT: {e}")
