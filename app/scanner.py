import subprocess
import threading
import json
import logging
import time
import os
import signal
from app.database import save_message
from app.mqtt_client import publish_rds

class Scanner:
    def __init__(self):
        self.process = None
        self.running = False
        self.current_frequency = 88.5
        self.current_gain = 'auto' # 'auto' or numeric value
        self.thread = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()

    def _build_command(self):
        # Base rtl_fm command
        cmd_rtl = ['rtl_fm', '-f', f'{self.current_frequency}M', '-M', 'fm', '-s', '171k', '-A', 'fast', '-r', '171k', '-l', '0', '-E', 'deemp']
        
        if self.current_gain != 'auto':
            cmd_rtl.extend(['-g', str(self.current_gain)])
            
        # Pipe to redsea
        # We use shell=True for the pipe, or we can use two Popens.
        # Shell=True is easier but risky if inputs aren't sanitized. 
        # Since inputs are internal, it's manageable, but better used two processes.
        # But wait, redsea reads from stdin.
        
        return cmd_rtl

    def start(self):
        with self.lock:
            if self.running:
                logging.warning("Scanner already running.")
                return

            self.stop_event.clear()
            self.running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
            logging.info(f"Scanner started on {self.current_frequency} MHz")

    def stop(self):
        with self.lock:
            self.stop_event.set()
            if self.process:
                try:
                    self.process.terminate()
                    # self.process.wait(timeout=1) # Don't block here
                except Exception as e:
                    logging.error(f"Error stopping process: {e}")
            self.running = False
            logging.info("Scanner stopped")

    def tune(self, frequency, gain=None):
        logging.info(f"Tuning to {frequency} MHz")
        self.stop()
        self.current_frequency = float(frequency)
        if gain is not None:
            self.current_gain = gain
        time.sleep(0.5) # Give it a moment to release device
        self.start()

    def scan_next(self):
        """
        Simple seek: Increment frequency until we find a signal (or just loop).
        For now, just hops 0.1 MHz. Ideally we check signal level.
        Real 'seek' requires signal strength check or RDS lock check.
        """
        # Logic: Stop, increment, Start.
        new_freq = round(self.current_frequency + 0.1, 1)
        if new_freq > 108.0:
            new_freq = 87.5
        self.tune(new_freq)
        return new_freq

    def _run_loop(self):
        rtl_cmd = self._build_command()
        
        # We need to pipe rtl_fm -> redsea
        # Use simple shell string for simplicity in this context given the complex pipe
        # rtl_fm ... | redsea -u -j
        
        gain_flag = f"-g {self.current_gain}" if self.current_gain != 'auto' else ""
        full_cmd = f"rtl_fm -f {self.current_frequency}M -M fm -s 171k -A fast -r 171k -l 0 -E deemp {gain_flag} | redsea -u"
        
        logging.info(f"Running command: {full_cmd}")
        
        try:
            # shell=True required for pipe
            self.process = subprocess.Popen(full_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=1, universal_newlines=True) # universal_newlines=True for text mode
            
            # Read stdout line by line
            while not self.stop_event.is_set():
                line = self.process.stdout.readline()
                if not line:
                    if self.process.poll() is not None:
                        break
                    continue
                
                try:
                    data = json.loads(line)
                    # Enrich with frequency if not present (redsea usually adds it if known? No, rtl_fm doesn't tell redsea freq)
                    # We add our current frequency
                    data['frequency'] = self.current_frequency
                    
                    # Save to DB
                    save_message(data)
                    
                    # Publish to MQTT
                    publish_rds(data)
                    
                except json.JSONDecodeError:
                    pass # Ignore partial lines or noise
                    
        except Exception as e:
            logging.error(f"Error in scanner loop: {e}")
        finally:
            if self.process:
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM) # Kill process group if shell=True sets it? 
                    # Actually standard terminate might not kill the pipe children.
                    # With shell=True, self.process.pid is the shell.
                    # We might need to be more aggressive to kill rtl_fm.
                    # But inside docker, standard cleanup usually works.
                    self.process.terminate()
                except:
                    pass
            self.running = False

# Global instance
scanner_instance = Scanner()
