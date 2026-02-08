"""
DAB (Digital Audio Broadcasting) scanner controller.
Uses welle-cli with built-in web server for DAB reception.
"""
import subprocess
import os
import signal
import threading
import logging
import time
import json
import sys
import requests
from app.database import get_settings

# Swedish DAB+ channels reference
DAB_CHANNELS = {
    '5A': 174928,  # kHz
    '5B': 176640,
    '5C': 178352,
    '5D': 180064,
    '6A': 181936,
    '6B': 183648,
    '6C': 185360,
    '6D': 187072,
    '7A': 188928,
    '7B': 190640,
    '7C': 192352,
    '7D': 194064,
    '8A': 195936,
    '8B': 197648,
    '8C': 199360,
    '8D': 201072,
    '9A': 202928,
    '9B': 204640,
    '9C': 206352,
    '9D': 208064,
    '10A': 209936,
    '10B': 211648,
    '10C': 213360,
    '10D': 215072,
    '11A': 216928,
    '11B': 218640,
    '11C': 220352,
    '11D': 222064,
    '12A': 223936,
    '12B': 225648,
    '12C': 227360,
    '12D': 229072,
    '13A': 230784,
    '13B': 232496,
    '13C': 234208,
    '13D': 235776,
    '13E': 237488,
    '13F': 239200,
}

class DABScanner:
    def __init__(self):
        self.process = None
        self.running = False
        self.current_channel = '12B'  # Default Swedish SR DAB
        self.current_service = None
        self.web_port = 7979
        self.lock = threading.Lock()
        self.services = []
        
    def start(self, channel=None):
        """Start welle-cli with web server on given channel."""
        if channel:
            self.current_channel = channel
            
        self.stop()  # Stop any existing process
        
        settings = get_settings()
        device = settings.get('device_index', '0')
        
        # welle-cli -c CHANNEL -w PORT starts the web server
        cmd = [
            'welle-cli',
            '-c', self.current_channel,
            '-w', str(self.web_port),
            '-D', device
        ]
        
        logging.info(f"Starting DAB on channel {self.current_channel}")
        
        try:
            popen_kwargs = {
                'stdout': subprocess.PIPE,
                'stderr': subprocess.PIPE,
            }
            if sys.platform != 'win32':
                popen_kwargs['preexec_fn'] = os.setsid
            
            self.process = subprocess.Popen(cmd, **popen_kwargs)
            self.running = True
            
            # Wait a moment for welle-cli to start
            time.sleep(2)
            
            # Start background thread to monitor
            threading.Thread(target=self._monitor_services, daemon=True).start()
            
            return True
        except Exception as e:
            logging.error(f"Failed to start DAB: {e}")
            return False
    
    def stop(self):
        """Stop the DAB receiver."""
        with self.lock:
            if self.process:
                try:
                    if sys.platform != 'win32':
                        os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                    else:
                        self.process.terminate()
                except Exception as e:
                    logging.debug(f"DAB stop error: {e}")
                self.process = None
            self.running = False
            self.services = []
            logging.info("DAB stopped")
    
    def tune_channel(self, channel):
        """Switch to a different DAB channel."""
        if channel not in DAB_CHANNELS:
            logging.error(f"Unknown DAB channel: {channel}")
            return False
        
        self.current_channel = channel
        return self.start(channel)
    
    def tune_service(self, service_id):
        """Tune to a specific service within current ensemble."""
        self.current_service = service_id
        # With welle-cli web interface, service selection is done via the web API
        try:
            response = requests.post(
                f'http://localhost:{self.web_port}/api/channel/{service_id}',
                timeout=5
            )
            return response.ok
        except:
            return False
    
    def _monitor_services(self):
        """Background thread to poll welle-cli web API for services."""
        while self.running:
            try:
                response = requests.get(
                    f'http://localhost:{self.web_port}/api/mux',
                    timeout=5
                )
                if response.ok:
                    data = response.json()
                    self.services = data.get('services', [])
            except:
                pass
            time.sleep(3)
    
    def get_services(self):
        """Get list of services in current ensemble."""
        return self.services
    
    def get_status(self):
        """Get current DAB status."""
        return {
            'running': self.running,
            'channel': self.current_channel,
            'service': self.current_service,
            'services': self.services,
            'web_port': self.web_port
        }
    
    def get_audio_url(self):
        """Get URL for audio stream from welle-cli."""
        if not self.running:
            return None
        return f'http://localhost:{self.web_port}/mp3'

# Singleton instance
dab_scanner = DABScanner()
