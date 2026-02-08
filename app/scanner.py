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
        self.stop()
        time.sleep(1) 
        settings = get_settings()
        integration = settings.get('scan_integration', '0.2')
        device = settings.get('device_index', '0')
        
        cmd = ['rtl_power', '-d', device, '-f', '87.5M:108M:100k', '-i', integration]
        
        if self.current_gain != 'auto':
            cmd.extend(['-g', str(self.current_gain)])
            
        cmd.extend(['-1', 'scan.csv'])
        try:
            subprocess.run(cmd, check=True, timeout=15)
            peaks = []
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
                                 peaks.append((freq_mhz, db))
            peaks.sort(key=lambda x: x[1], reverse=True)
            strongest = peaks[:40] # Analyze top 40 peaks
            strongest.sort(key=lambda x: x[0]) 
            return strongest
        except Exception as e:
            logging.error(f"Error during band scan: {e}")
            return []
        finally:
            if os.path.exists('scan.csv'):
                os.remove('scan.csv')

    def start_auto_search(self):
        """Starts the intelligent search process."""
        logging.info("Intelligent auto-search triggered.")
        self.searching = True
        self.scan_next()

    def scan_next(self):
        peaks = self.scan_band()
        if not peaks:
            self.searching = False
            return self.current_frequency

        next_freq = None
        for f, db in peaks:
            if f > self.current_frequency + 0.05:
                next_freq = f
                break
        
        if next_freq is None:
            next_freq = peaks[0][0]
        
        logging.info(f"Trying frequency: {next_freq} MHz")
        self.search_start_time = time.time()
        self.tune(next_freq)
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
                    if elapsed > 4.0: # 4 second timeout for RDS lock
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
                        logging.info(f"RDS Locked on {self.current_frequency} MHz! Stopping search.")
                        self.searching = False 

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
