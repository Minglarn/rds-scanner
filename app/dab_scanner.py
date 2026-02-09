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
from app.database import get_settings, save_message

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
        self.current_gain = 'auto'
        self.current_service = None
        self.web_port = 7979
        self.lock = threading.Lock()
        self.services = []
        
    def find_channel_by_freq(self, freq_mhz):
        """Find the DAB channel label for a given frequency in MHz."""
        try:
            freq_khz = int(float(freq_mhz) * 1000)
            # Small tolerance for floating point or rounding issues
            for label, khz in DAB_CHANNELS.items():
                if abs(khz - freq_khz) <= 5: # 5 kHz tolerance
                    return label
        except:
            pass
        return None

    def start(self, channel=None, gain=None):
        """Start welle-cli with web server on given channel."""
        if channel:
            self.current_channel = channel
        if gain is not None:
            self.current_gain = gain
            
        self.stop()  # Stop any existing process
        
        settings = get_settings()
        device = settings.get('device_index', '0')
        
        # welle-cli -c CHANNEL -w PORT starts the web server
        # We use -F soapysdr for explicit device selection by serial number
        cmd = [
            'welle-cli',
            '-c', self.current_channel,
            '-w', str(self.web_port),
        ]
        
        # If device looks like a serial number (more than 2 chars or non-digit)
        if len(device) > 2 or not device.isdigit():
            # Use -F soapysdr for input type, -s for device arguments
            cmd.extend(['-F', 'soapysdr'])
            cmd.extend(['-s', f'driver=rtlsdr,serial={device}'])
        else:
            # Traditional index - also use SoapySDR for consistency
            cmd.extend(['-F', 'soapysdr'])
            cmd.extend(['-s', f'driver=rtlsdr,rtl={device}'])
        
        # Add gain if specified (and not auto)
        # welle-cli uses -g GAIN
        if self.current_gain != 'auto':
            cmd.extend(['-g', str(self.current_gain)])
        else:
            # "Auto" gain in UI -> Force high gain (40) because default is often 0
            cmd.extend(['-g', '40'])
        
        logging.info(f"Starting DAB on channel {self.current_channel}")
        logging.info(f"DAB command: {' '.join(cmd)}")
        
        # Try up to 3 times to start welle-cli (USB might be slow to release)
        for attempt in range(3):
            try:
                popen_kwargs = {
                    'stdout': subprocess.PIPE,
                    'stderr': subprocess.PIPE,
                }
                if sys.platform != 'win32':
                    # Use start_new_session for proper process group handling
                    popen_kwargs['start_new_session'] = True
                
                self.process = subprocess.Popen(cmd, **popen_kwargs)
                self.running = True
                
                # Wait for process to start and stay alive
                time.sleep(2)
                if self.process.poll() is not None:
                    # welle-cli exited immediately, probably device busy
                    stderr_out = self.process.stderr.read().decode('utf-8', errors='ignore')
                    if "usb_claim_interface error" in stderr_out or "device busy" in stderr_out.lower():
                        logging.warning(f"DAB start attempt {attempt+1} failed (device busy), retrying...")
                        self.stop()
                        time.sleep(1.5)
                        continue
                
                # Start background thread to monitor services via API
                threading.Thread(target=self._monitor_services, daemon=True).start()

                # Start background thread to log welle-cli output
                def _log_output(pipe, level):
                    try:
                        for line in iter(pipe.readline, b''):
                            line_str = line.decode('utf-8', errors='ignore').strip()
                            if line_str:
                                # Filter out noisy internal messages
                                if "Could not understand GET request" in line_str:
                                    continue
                                if "SuperframeFilter" in line_str:
                                    continue
                                logging.info(f"welle-cli: {line_str}")
                    except Exception:
                        pass

                threading.Thread(target=_log_output, args=(self.process.stdout, logging.INFO), daemon=True).start()
                threading.Thread(target=_log_output, args=(self.process.stderr, logging.ERROR), daemon=True).start()
                
                return True
            except Exception as e:
                logging.error(f"DAB start attempt {attempt+1} error: {e}")
                time.sleep(1)
        
        return False
    
    def stop(self):
        """Stop the DAB receiver."""
        with self.lock:
            if self.process:
                try:
                    if sys.platform != 'win32':
                        # Try SIGTERM first
                        try:
                            os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                            # Wait a bit
                            try:
                                self.process.wait(timeout=1)
                            except subprocess.TimeoutExpired:
                                # Force kill if still running
                                logging.warning("DAB process didn't stop, forcing usage of SIGKILL")
                                os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                        except Exception:
                            pass
                    else:
                        self.process.terminate()
                except Exception as e:
                    logging.debug(f"DAB stop error: {e}")
                self.process = None
            
            # Ensure internal state is reset
            self.running = False
            self.services = []
            logging.info("DAB stopped")
    
    def tune_channel(self, channel):
        """Switch to a different DAB channel."""
        if channel not in DAB_CHANNELS:
            logging.error(f"Unknown DAB channel: {channel}")
            return False
        
        # Skip restart if already running on this channel
        if self.running and self.current_channel == channel:
            logging.info(f"DAB already running on {channel}, skipping restart")
            return True
        
        self.current_channel = channel
        return self.start(channel)
        
    def set_gain(self, gain):
        """Set tuner gain."""
        self.current_gain = gain
        # Restart required to change gain
        return self.start()
    
    def tune_service(self, service_id):
        """Tune to a specific service within current ensemble."""
        self.current_service = service_id
        # With welle-cli web interface, service selection is done via the web API
        # Try different endpoint formats that welle-cli might use
        try:
            # Try /channel?sid=xxx format (common in welle-cli)
            response = requests.get(
                f'http://localhost:{self.web_port}/channel?sid={service_id}',
                timeout=5
            )
            if response.ok:
                logging.info(f"DAB: Tuned to service {service_id}")
                return True
            
            # Fallback: Try POST to /api/channel
            response = requests.post(
                f'http://localhost:{self.web_port}/api/channel/{service_id}',
                timeout=5
            )
            if response.ok:
                logging.info(f"DAB: Tuned to service {service_id} via /api/channel")
                return True
                
            logging.warning(f"DAB: Could not tune to service {service_id}: {response.status_code}")
            return False
        except Exception as e:
            logging.error(f"DAB: Error tuning to service: {e}")
            return False
    
    def _get_channel_freq(self):
        """Get the frequency in MHz for the current channel."""
        if self.current_channel and self.current_channel in DAB_CHANNELS:
            return DAB_CHANNELS[self.current_channel] / 1000.0  # kHz to MHz
        return 0.0
    
    def _monitor_services(self):
        """Background thread to poll welle-cli web API for services."""
        import re
        while self.running:
            try:
                # Try /mux.json (seen in HTML)
                response = requests.get(
                    f'http://localhost:{self.web_port}/mux.json',
                    timeout=5
                )
                if response.ok:
                    data = response.json()
                    raw_services = data.get('services', [])
                    clean_services = []
                    for s in raw_services:
                        # Extract SID
                        sid = s.get('sid', '')
                        # Extract Name from nested label object if necessary
                        label_val = s.get('label', 'Unknown')
                        name = "Unknown"
                        if isinstance(label_val, dict):
                            name = label_val.get('label', '').strip() or label_val.get('shortlabel', '').strip()
                        elif isinstance(label_val, str):
                            name = label_val.strip()
                        
                        # Add normalized service
                        # We keep original fields just in case, but ensure 'name' and 'id' vary
                        s['name'] = name
                        s['id'] = sid
                        clean_services.append(s)
                    
                    # Only log if service count changed
                    if len(clean_services) != len(self.services):
                        logging.info(f"DAB: Found {len(clean_services)} services. First: {clean_services[0].get('name') if clean_services else 'N/A'}")
                        
                        # Save new services to database as station cards
                        existing_sids = {s.get('id') for s in self.services}
                        for svc in clean_services:
                            if svc.get('id') not in existing_sids:
                                # Map DAB fields to RDS-like fields for compatibility
                                save_message({
                                    'frequency': self._get_channel_freq(),
                                    'pi': svc.get('id', ''),
                                    'ps': svc.get('name', 'Unknown'),
                                    'rt': f"DAB+ service on {self.current_channel}",
                                    'prog_type': svc.get('ptystring', ''),
                                    'dab': True  # Flag to identify DAB entries
                                })
                    self.services = clean_services
                else:
                    # Try /api/mux (older versions?)
                    response = requests.get(
                        f'http://localhost:{self.web_port}/api/mux',
                        timeout=5
                    )
                    if response.ok:
                        data = response.json()
                        self.services = data.get('services', [])
                    else:
                        logging.warning(f"Failed to get services: {response.status_code}")
                            
            except Exception as e:
                logging.error(f"DAB polling error: {e}") 
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
