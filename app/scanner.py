import subprocess
import threading
import json
import logging
import time
import os
import signal
import csv
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

    def scan_band(self):
        """
        Perform a wideband scan using rtl_power to find strong signals.
        Returns a sorted list of (frequency, db) tuples.
        """
        logging.info("Starting wideband scan...")
        self.stop()
        time.sleep(1) # Ensure device is released
        
        # Scan 87.5M to 108M with 100k bins. 
        # -i 1s (integration interval). -1 (single shot)
        # Output to stdout (or temp file). stdout is -
        
        cmd = ['rtl_power', '-f', '87.5M:108M:100k', '-i', '0.2', '-g', '50', '-1', 'scan.csv']
        
        try:
            subprocess.run(cmd, check=True, timeout=15)
            
            peaks = []
            with open('scan.csv', 'r') as f:
                reader = csv.reader(f)
                for row in reader:
                    # rtl_power csv format:
                    # date, time, Hz low, Hz high, Hz step, samples, dB, dB, dB...
                    # We need to map dB values to frequencies.
                    if len(row) < 7: continue
                    
                    start_freq = float(row[2])
                    step = float(row[4])
                    db_values = [float(x) for x in row[6:]]
                    
                    for i, db in enumerate(db_values):
                        freq = start_freq + (i * step)
                        freq_mhz = round(freq / 1000000, 1)
                        if freq_mhz >= 87.5 and freq_mhz <= 108.0:
                             peaks.append((freq_mhz, db))
            
            # Simple peak detection:
            # 1. Filter out noise (e.g. < -10 dB? dynamic?)
            # Let's take the top 20 strongest signals
            peaks.sort(key=lambda x: x[1], reverse=True)
            strongest = peaks[:30]
            strongest.sort(key=lambda x: x[0]) # Sort by frequency
            
            logging.info(f"Scan complete. Found {len(strongest)} peaks.")
            return strongest

        except Exception as e:
            logging.error(f"Error during band scan: {e}")
            return []
        finally:
            if os.path.exists('scan.csv'):
                os.remove('scan.csv')

    def scan_next(self):
        """
        Finds the next strong signal after the current frequency.
        If no peaks are cached or valid, falls back to incrementing.
        """
        # For now, we do a fresh scan every time? Or cache?
        # A fresh scan takes ~2-5s.
        # User wants "Scan Next".
        
        peaks = self.scan_band()
        
        if not peaks:
            logging.warning("No peaks found, falling back to simple step.")
            new_freq = round(self.current_frequency + 0.1, 1)
            if new_freq > 108.0: new_freq = 87.5
            self.tune(new_freq)
            return new_freq

        # Find next freq in peaks > current_frequency
        next_freq = None
        for f, db in peaks:
            if f > self.current_frequency + 0.05: # Small buffer
                next_freq = f
                break
        
        if next_freq is None:
            # Wrap around to first peak
            if peaks:
                next_freq = peaks[0][0]
            else:
                next_freq = 87.5
        
        logging.info(f"Auto-scan found next peak: {next_freq} MHz")
        self.tune(next_freq)
        return next_freq

    def _run_loop(self):
        rtl_cmd = self._build_command()
        
        gain_flag = f"-g {self.current_gain}" if self.current_gain != 'auto' else ""
        full_cmd = f"rtl_fm -f {self.current_frequency}M -M fm -s 171k -A fast -r 171k -l 0 -E deemp {gain_flag} | redsea -u"
        
        logging.info(f"Running command: {full_cmd}")
        
        try:
            # shell=True required for pipe
            # setsid to create a new session group, easier to kill
            self.process = subprocess.Popen(full_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=1, universal_newlines=True, preexec_fn=os.setsid) 
            
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
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM) 
                except:
                    pass
            self.running = False

# Global instance
scanner_instance = Scanner()
