import paho.mqtt.client as mqtt
import os
import json
import logging

BROKER = os.getenv('MQTT_BROKER', 'localhost')
PORT = int(os.getenv('MQTT_PORT', 1883))
TOPIC_PREFIX = os.getenv('MQTT_TOPIC_PREFIX', 'rds')

client = None

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logging.info("Connected to MQTT Broker!")
    else:
        logging.error(f"Failed to connect, return code {rc}")

def init_mqtt():
    global client
    if BROKER == 'localhost':
        logging.warning("MQTT_BROKER not set, skipping MQTT init.")
        return

    client = mqtt.Client()
    client.on_connect = on_connect
    
    try:
        client.connect(BROKER, PORT, 60)
        client.loop_start()
    except Exception as e:
        logging.error(f"Could not connect to MQTT Broker: {e}")
        client = None

def publish_rds(data):
    if not client:
        return

    try:
        # Publish full JSON
        client.publish(f"{TOPIC_PREFIX}/json", json.dumps(data))
        
        # Publish specific fields for easier consumption
        if 'ps' in data:
            client.publish(f"{TOPIC_PREFIX}/ps", data['ps'])
        if 'rt' in data:
            client.publish(f"{TOPIC_PREFIX}/rt", data['rt'])
        if 'pi' in data:
            client.publish(f"{TOPIC_PREFIX}/pi", data['pi'])
        if 'pty' in data:
            client.publish(f"{TOPIC_PREFIX}/pty", str(data['pty']))
            
    except Exception as e:
        logging.error(f"Error publishing to MQTT: {e}")
