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
        self.scan_status = ""  # Human-readable status for UI
        self.scan_progress = 0  # Current station index
        self.scan_total = 0  # Total stations to scan
        self.stations_found = 0  # RDS stations found in this scan

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
        """Stop the scanner and release the device."""
        if not self.running and not self.process:
            return
        
        # Signal the thread to stop
        self.stop_event.set()
        
        # Kill the process if it exists
        with self.lock:
            if self.process:
                logging.debug("Stopping FM scanner process...")
                try:
                    if sys.platform != 'win32':
                        os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                        try:
                            self.process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            logging.warning("Scanner process didn't stop with SIGTERM, forcing SIGKILL")
                            os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                            self.process.wait(timeout=1)
                    else:
                        self.process.terminate()
                        self.process.wait(timeout=2)
                except Exception as e:
                    logging.debug(f"Stop error: {e}")
                
                self.process = None
        
        # Wait for the thread to actually exit
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)
            if self.thread.is_alive():
                logging.warning("Scanner thread did not exit cleanly")
        
        # Nuclear option: kill rtl_fm by name to be absolutely sure
        try:
            subprocess.run(['pkill', '-9', 'rtl_fm'], stderr=subprocess.DEVNULL, timeout=1)
            subprocess.run(['pkill', '-9', 'redsea'], stderr=subprocess.DEVNULL, timeout=1)
        except:
            pass
        
        self.running = False
        logging.info("Scanner stopped")

    def tune(self, frequency, gain=None):
        logging.info(f"Tuning to {frequency} MHz")
        # Manual tune always stops auto-search
        self.searching = False
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
        """Toggle auto-search on/off."""
        if self.searching:
            # User wants to STOP the search
            logging.info("Stopping auto-search by user request.")
            self.searching = False
            self.scan_status = "Scan aborted"
            return
        
        # Start fresh search
        def _full_band_scan():
            logging.info("=== FULL BAND SCAN STARTING ===")
            self.searching = True
            self.peak_cache = []  # Clear cache to force fresh scan
            self.stations_found = 0
            self.scan_status = "Scanning FM band for signals..."
            
            # First, do full band power scan to find all peaks
            peaks = self.scan_band()
            if not peaks:
                logging.warning("No peaks found. Aborting scan.")
                self.searching = False
                self.scan_status = "No signals found"
                self.start()  # Resume normal listening
                return
            
            self.scan_total = len(peaks)
            logging.info(f"Found {len(peaks)} potential stations. Scanning each...")
            
            # Now visit each peak sequentially
            for i, freq in enumerate(peaks):
                if not self.searching:
                    logging.info("Scan aborted by user.")
                    self.scan_status = "Scan aborted by user"
                    break
                
                self.scan_progress = i + 1
                self.scan_status = f"Checking {freq} MHz ({i+1}/{len(peaks)})"
                logging.info(f"[{i+1}/{len(peaks)}] Checking {freq} MHz...")
                self.current_frequency = freq
                self.stop()
                time.sleep(0.3)
                
                # Start listening and wait for RDS
                found = self._listen_for_rds(freq, timeout=2.5)
                if found:
                    self.stations_found += 1
            
            # Scan complete
            self.scan_status = f"Complete! Found {self.stations_found} stations"
            logging.info(f"=== FULL BAND SCAN COMPLETE: {self.stations_found} stations found ===")
            self.searching = False
            self.start()  # Resume normal listening on last freq
        
        threading.Thread(target=_full_band_scan, daemon=True).start()
    
    def _listen_for_rds(self, freq, timeout=2.5):
        """Listen on a frequency for RDS data. Save if found."""
        import queue
        settings = get_settings()
        device = settings.get('device_index', '0')
        
        gain_val = self.current_gain
        if gain_val != 'auto' and float(gain_val) == 0:
            gain_val = 0.1
        gain_flag = f"-g {gain_val}" if self.current_gain != 'auto' else ""
        
        full_cmd = f"rtl_fm -d {device} -f {freq}M -M fm -s 171k -A fast -r 171k -l 0 -E deemp {gain_flag} | redsea -u"
        
        try:
            process = subprocess.Popen(full_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, 
                                       bufsize=1, universal_newlines=True, preexec_fn=os.setsid)
            
            q = queue.Queue()
            def reader(pipe, q):
                try:
                    for line in iter(pipe.readline, ''):
                        if not line: break
                        q.put(line)
                except: pass
                finally: pipe.close()
            
            reader_thread = threading.Thread(target=reader, args=(process.stdout, q), daemon=True)
            reader_thread.start()
            
            start_time = time.time()
            found_rds = False
            
            while time.time() - start_time < timeout:
                if not self.searching:
                    break
                try:
                    line = q.get(timeout=0.3)
                    data = json.loads(line)
                    data['frequency'] = freq
                    
                    if data.get('pi') or data.get('ps') or data.get('rt'):
                        found_rds = True
                        save_message(data)
                        publish_rds(data)
                        logging.info(f"RDS found on {freq} MHz: {data.get('ps', '?')}")
                except:
                    pass
            
            # Cleanup
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except:
                pass
            
            if not found_rds:
                logging.debug(f"No RDS on {freq} MHz")
            
            return found_rds
                
        except Exception as e:
            logging.error(f"Error listening on {freq}: {e}")
            return False


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
            # Use start_new_session for proper process group handling
            self.process = subprocess.Popen(full_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=1, universal_newlines=True, start_new_session=True) 
            
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
                try:
                    line = q.get(timeout=0.5) # Check stop_event every 0.5s even if no data
                except queue.Empty:
                    if self.process is None or self.process.poll() is not None:
                        break
                    continue
                
                try:
                    data = json.loads(line)
                    data['frequency'] = self.current_frequency
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
