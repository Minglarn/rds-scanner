# RDS Scanner (Dockerized)

A Dockerized application for monitoring **FM radio** and **DAB/DAB+** signals, decoding RDS data, and publishing it to MQTT. This project uses an RTL-SDR dongle and integrates `rtl_fm`, `redsea`, `welle-cli`, and a Flask-based Web UI.

## Features

### FM Radio
- **RTL-SDR Integration**: Decodes FM radio signals using `rtl_fm` and `redsea`.
- **RDS Decoding**: Captures Program Identification (PI), Program Service (PS), Radio Text (RT), Program Type (PTY), and flags (TMC, TA, TP).
- **Full Band Scan**: Automatic scanning of the entire FM band (87.5 - 108.0 MHz) with peak detection.
- **Live Audio Streaming**: Listen to FM radio directly in your browser.

### DAB/DAB+ Radio
- **Digital Audio Broadcasting**: Receive DAB+ stations using `welle-cli`.
- **Ensemble/Service Selection**: Browse available DAB channels and services.
- **Live DAB Audio**: Stream DAB audio via the integrated web player.

### Common Features
- **FM/DAB Mode Toggle**: Switch between FM and DAB with a single click.
- **Web Interface**:
    - Live view of received RDS messages with station cards.
    - Controls for Frequency/Channel, RF Gain, and audio playback.
    - Status indicators for traffic flags (TMC, TA, TP).
    - Sorting by Frequency, Station Name, Program Type, or Last Seen.
- **MQTT Support**: Publishes decoded data to an MQTT broker for Home Assistant integration.
- **Persistent Storage**: Stores all received messages in an SQLite database.

## Prerequisites

- Docker and Docker Compose installed.
- RTL-SDR USB dongle connected to the host machine.
- (Optional) MQTT Broker (e.g., Mosquitto) for data publishing.

## Usage

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/Minglarn/rds-scanner.git
    cd rds-scanner
    ```

2.  **Configure MQTT (Optional)**:
    Edit `docker-compose.yml` to set your MQTT broker details:
    ```yaml
    environment:
      - MQTT_BROKER=your_mqtt_broker_ip
      - MQTT_PORT=1883
      - MQTT_TOPIC_PREFIX=rds
    ```

3.  **Build and Run**:
    ```bash
    docker-compose up -d --build
    ```
    *Note: The container needs access to the USB device. The `docker-compose.yml` is configured to map `/dev/bus/usb`.*

4.  **Access the Web Interface**:
    Open your browser and navigate to `http://localhost:9000`.

## API Endpoints

### FM Radio
- `GET /api/status`: Get current tuner status (frequency, gain, scan progress).
- `POST /api/tune`: Set frequency or gain. Body: `{"frequency": 98.5}` or `{"gain": 40}`
- `POST /api/scan/next`: Start/stop full band scan.
- `GET /api/messages`: Retrieve saved stations. Params: `?sort=frequency|ps|pty|last_seen`
- `GET /api/audio/stream`: Live FM audio stream. Params: `?freq=98.5`

### DAB Radio
- `GET /api/mode`: Get current mode (fm or dab).
- `POST /api/mode`: Switch mode. Body: `{"mode": "dab"}`
- `GET /api/dab/status`: Get DAB receiver status and services.
- `GET /api/dab/channels`: List available DAB channels.
- `POST /api/dab/tune`: Tune to channel or service. Body: `{"channel": "12B"}` or `{"service": "P1"}`
- `GET /api/dab/audio`: Stream DAB audio.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Web Interface                     │
│  FM Controls │ DAB Controls │ Live Audio Player     │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│                  Flask Backend                       │
│  /api/tune │ /api/mode │ /api/dab/* │ /api/audio   │
└─────────────────────────────────────────────────────┘
        │                           │
        ▼                           ▼
┌───────────────────┐     ┌───────────────────────────┐
│   FM Mode         │     │   DAB Mode                │
│   rtl_fm + redsea │     │   welle-cli               │
│   + ffmpeg audio  │     │   (built-in web server)   │
└───────────────────┘     └───────────────────────────┘
```

## Development

- **Backend**: Python (Flask)
- **Frontend**: HTML/CSS with HTMX for dynamic updates
- **FM Decoding**: `rtl_fm` + `redsea`
- **DAB Decoding**: `welle-cli` (headless mode)
- **Audio Encoding**: `ffmpeg` (FM) / native (DAB)
- **Database**: SQLite (`data/rds.db`)

## Swedish DAB+ Channels (Reference)

| Channel | Frequency   | Notes              |
|---------|-------------|--------------------|
| 5A      | 174.928 MHz |                    |
| 7D      | 194.064 MHz |                    |
| 11C     | 220.352 MHz |                    |
| 12A     | 223.936 MHz |                    |
| 12B     | 225.648 MHz | Sveriges Radio DAB |
| 12C     | 227.360 MHz |                    |

## License

MIT License
