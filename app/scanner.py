import subprocess
import threading
import json
import logging
import time
import os
import signal
import csv
from app.database import save_message, get_settings
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
        
        # Search state
        self.searching = False
        self.last_rds_time = 0
        self.search_start_time = 0
        self.peak_cache = []

    def _build_command(self):
        settings = get_settings()
        device = settings.get('device_index', '0')
        
        cmd_rtl = ['rtl_fm', '-d', device, '-f', f'{self.current_frequency}M', '-M', 'fm', '-s', '171k', '-A', 'fast', '-r', '171k', '-l', '0', '-E', 'deemp']
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
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                except:
                    pass
            self.running = False
            logging.info("Scanner stopped")

    def tune(self, frequency, gain=None):
        logging.info(f"Tuning to {frequency} MHz")
        self.stop()
        self.current_frequency = float(frequency)
        if gain is not None:
            self.current_gain = gain
        time.sleep(0.5) 
        self.start()

    def scan_band(self):
        logging.info("Starting wideband scan...")
        self.stop() # CRITICAL: Stop rtl_fm so rtl_power can use the device
        time.sleep(2.0) # Give device time to settle
        settings = get_settings()
        integration = settings.get('scan_integration', '0.2')
        device = settings.get('device_index', '0')
        squelch = float(settings.get('squelch_threshold', '-40'))
        
        cmd = ['rtl_power', '-d', device, '-f', '87.5M:108M:100k', '-i', integration]
        if self.current_gain != 'auto':
            cmd.extend(['-g', str(self.current_gain)])
            
        cmd.extend(['-1', 'scan.csv'])
        try:
            # Increase timeout to 30s to be safe
            subprocess.run(cmd, check=True, timeout=30)
            
            # Collect ALL signal data for smart analysis
            all_signals = []  # List of (freq_mhz, db_value)
            
            if os.path.exists('scan.csv'):
                with open('scan.csv', 'r') as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if len(row) < 7: continue
                        start_freq = float(row[2])
                        step = float(row[4])
                        db_values = [float(x) for x in row[6:]]
                        for i, db in enumerate(db_values):
                            freq = start_freq + (i * step)
                            freq_mhz = round(freq / 1000000, 1)
                            if 87.5 <= freq_mhz <= 108.0:
                                all_signals.append((freq_mhz, db))
            
            # Sort by frequency
            all_signals.sort(key=lambda x: x[0])
            
            # Find LOCAL MAXIMA (peaks that are stronger than neighbors)
            # A real station should be a peak in signal strength
            peaks = []
            for i in range(2, len(all_signals) - 2):
                freq, db = all_signals[i]
                
                # Must be above squelch threshold
                if db < squelch:
                    continue
                
                # Check if this is a local maximum (higher than 2 neighbors on each side)
                neighbors = [all_signals[i-2][1], all_signals[i-1][1], 
                            all_signals[i+1][1], all_signals[i+2][1]]
                
                if db > max(neighbors):
                    # This is a true peak - a local maximum above threshold
                    peaks.append(freq)
                    logging.debug(f"Peak found: {freq} MHz at {db:.1f} dB")
            
            # Deduplicate (merge peaks within 0.15 MHz of each other - sidebands)
            merged_peaks = []
            for freq in peaks:
                if not merged_peaks or freq - merged_peaks[-1] > 0.15:
                    merged_peaks.append(freq)
            
            logging.info(f"Band scan complete. Found {len(merged_peaks)} real stations (squelch: {squelch} dB).")
            
            return merged_peaks
        except Exception as e:
            logging.error(f"Error during band scan: {e}")
            return []
        finally:
            if os.path.exists('scan.csv'):
                os.remove('scan.csv')

    def start_auto_search(self):
        """Starts the intelligent search process in a background thread."""
        if self.searching:
            logging.info("Search already in progress, skipping request.")
            return
            
        def _search_thread():
            logging.info("Intelligent auto-search starting...")
            self.searching = True
            self.scan_next()

        threading.Thread(target=_search_thread, daemon=True).start()

    def scan_next(self):
        # Use cache if available
        if not self.peak_cache:
            logging.info("Peak cache empty. Scanning entire band...")
            self.peak_cache = self.scan_band()
        
        if not self.peak_cache:
            logging.warning("No peaks found after scan. Aborting search.")
            self.searching = False
            # Restart normal monitoring loop on current freq
            self.start()
            return self.current_frequency

        # Find next frequency in cache
        next_freq = None
        for f in self.peak_cache:
            if f > self.current_frequency + 0.05: 
                next_freq = f
                break
        
        if next_freq is None:
            logging.info("End of band reached, wrapping to start of cache.")
            next_freq = self.peak_cache[0]
        
        logging.info(f"Next Station: {next_freq} MHz (from {len(self.peak_cache)} peaks)")
        self.search_start_time = time.time()
        self.tune(next_freq)
        
        # We return the freq but finding the next one is done by calling scan_next again 
        # via the loop timeout or manual button. 
        return next_freq

    def _run_loop(self):
        import queue
        settings = get_settings()
        device = settings.get('device_index', '0')
        
        # If gain is 0 but manual, we use 0.1 to avoid triggering "auto" in some rtl versions
        gain_val = self.current_gain
        if gain_val != 'auto' and float(gain_val) == 0:
            gain_val = 0.1
            
        gain_flag = f"-g {gain_val}" if self.current_gain != 'auto' else ""
        full_cmd = f"rtl_fm -d {device} -f {self.current_frequency}M -M fm -s 171k -A fast -r 171k -l 0 -E deemp {gain_flag} | redsea -u"
        
        try:
            self.process = subprocess.Popen(full_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=1, universal_newlines=True, preexec_fn=os.setsid) 
            
            q = queue.Queue()
            def reader(pipe, q):
                try:
                    for line in iter(pipe.readline, ''):
                        if not line: break
                        q.put(line)
                except: pass
                finally: pipe.close()

            reader_thread = threading.Thread(target=reader, args=(self.process.stdout, q), daemon=True)
            reader_thread.start()

            while not self.stop_event.is_set():
                # Check search timeout (if no RDS within 4 seconds, skip to next)
                if self.searching:
                    elapsed = time.time() - self.search_start_time
                    if elapsed > 2.0: # 2 second timeout for RDS lock (faster scan)
                        logging.info(f"No RDS lock on {self.current_frequency} MHz after {round(elapsed, 1)}s. Skipping...")
                        # Run scan_next in a thread so we don't block this breaking loop
                        threading.Thread(target=self.scan_next, daemon=True).start()
                        break 

                try:
                    line = q.get(timeout=0.5) # Check stop_event every 0.5s even if no data
                except queue.Empty:
                    if self.process.poll() is not None:
                        break
                    continue
                
                try:
                    data = json.loads(line)
                    data['frequency'] = self.current_frequency
                    
                    if self.searching and (data.get('pi') or data.get('ps') or data.get('rt')):
                        # Found RDS! 
                        # User wants full band scan, so we don't stop.
                        # We linger for 3 seconds to get good data, then move on.
                        elapsed_lock = time.time() - self.last_rds_time
                        if elapsed_lock > 3.0: 
                             logging.info(f"RDS captured on {self.current_frequency}. Moving to next...")
                             self.last_rds_time = time.time() # Reset for debounce
                             threading.Thread(target=self.scan_next, daemon=True).start()
                        else:
                             # Just update timestamps so we don't move too fast
                             self.last_rds_time = time.time()

                    save_message(data)
                    publish_rds(data)
                    
                except json.JSONDecodeError:
                    pass 
                    
        except Exception as e:
            logging.error(f"Error in scanner loop: {e}")
        finally:
            if self.process:
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM) 
                except:
                    pass
            self.running = False

scanner_instance = Scanner()
