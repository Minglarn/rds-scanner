# Changelog

All notable changes to this project will be documented in this file.

## [0.3.0] - 2026-02-08

### Added
- **DAB/DAB+ Radio Support**
  - New `welle-cli` integration for DAB reception
  - FM/DAB mode toggle switch in header
  - DAB channel selector (Swedish channels: 5A-13F)
  - DAB service browser with automatic discovery
  - Live DAB audio streaming
  
- **FM Audio Streaming**
  - Live FM audio playback via browser
  - `rtl_fm` → `ffmpeg` → HTTP MP3 stream
  - LISTEN/STOP toggle button
  
- **Station Sorting**
  - Sort dropdown: Frequency, Station Name, Program Type, Last Seen
  - Default sort by frequency (prevents card jumping)

### Changed
- Dockerfile now builds both `redsea` (FM) and `welle-cli` (DAB)
- Added `sox` and `ffmpeg` for audio processing
- Exposed port 7979 for welle-cli web interface
- Increased default message limit from 15 to 50

---

## [0.2.0] - 2026-02-08

### Added
- **Full Band Scan**
  - Toggle scan with start/stop button
  - Progress display (X/Y frequencies)
  - Peak detection with SNR threshold
  - Real-time station count during scan

- **Scan Status Display**
  - Progress shown in RDS panel during scan
  - "SCANNING..." indicator with found count
  - Completion message when scan finishes

### Changed
- Scan button changes to red "STOP SCAN" during active scan
- Status polling increases to 1s during scan (normally 3s)

---

## [0.1.0] - 2026-02-08

### Added
- Initial release
- RTL-SDR FM radio monitoring
- RDS decoding (PI, PS, RT, PTY, TMC, TA, TP)
- Flask web interface with retro "tactical" styling
- MQTT publishing
- SQLite database storage
- Station card display with grouping
- Manual frequency tuning
- Gain control (manual and auto)
- Settings page for device configuration
