"""
Audio streaming module for FM radio playback.
Streams live audio from rtl_fm through the web interface.
"""
import subprocess
import os
import signal
import threading
import logging
import sys
from flask import Response
from app.database import get_settings

class AudioStreamer:
    def __init__(self):
        self.process = None
        self.lock = threading.Lock()
    
    def _build_command(self, frequency, gain='auto'):
        """Build the rtl_fm + sox + ffmpeg pipeline for audio streaming."""
        settings = get_settings()
        device = settings.get('device_index', '0')
        
        # Build gain flag
        gain_flag = "" if gain == 'auto' else f"-g {gain}"
        
        # rtl_fm outputs raw signed 16-bit mono audio at given sample rate
        # We use sox to resample to 44100Hz, then ffmpeg to encode to MP3
        cmd = (
            f"rtl_fm -d {device} -f {frequency}M -M fm -s 171k -A fast -r 44100 -l 0 -E deemp {gain_flag} | "
            f"ffmpeg -f s16le -ar 44100 -ac 1 -i - -acodec libmp3lame -ab 128k -f mp3 -"
        )
        return cmd
    
    def generate_audio(self, frequency, gain='auto'):
        """Generator that yields audio chunks for streaming."""
        cmd = self._build_command(frequency, gain)
        logging.info(f"Starting audio stream: {frequency} MHz")
        
        try:
            # preexec_fn only works on Unix
            popen_kwargs = {
                'shell': True,
                'stdout': subprocess.PIPE,
                'stderr': subprocess.DEVNULL,
            }
            if sys.platform != 'win32':
                popen_kwargs['preexec_fn'] = os.setsid
            
            process = subprocess.Popen(cmd, **popen_kwargs)
            
            with self.lock:
                self.process = process
            
            # Yield audio chunks
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                yield chunk
                
        except GeneratorExit:
            # Client disconnected
            logging.info("Audio stream: Client disconnected")
        except Exception as e:
            logging.error(f"Audio stream error: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """Stop the current audio stream."""
        with self.lock:
            if self.process:
                try:
                    if sys.platform != 'win32':
                        os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                    else:
                        self.process.terminate()
                except Exception as e:
                    logging.debug(f"Stop process error: {e}")
                self.process = None
                logging.info("Audio stream stopped")

# Singleton instance
audio_streamer = AudioStreamer()

def get_audio_stream(frequency, gain='auto'):
    """Return a Flask Response with streaming audio."""
    return Response(
        audio_streamer.generate_audio(frequency, gain),
        mimetype='audio/mpeg',
        headers={
            'Cache-Control': 'no-cache, no-store',
            'Connection': 'keep-alive',
        }
    )
