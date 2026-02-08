# RDS Scanner (Dockerized)

A Dockerized application for monitoring FM radio signals, decoding RDS/RBDS data, and publishing it to MQTT. This project uses an RTL-SDR dongle and integrates `rtl_fm`, `redsea`, `sqlite`, and a Flask-based Web UI.

## Features

- **RTL-SDR Integration**: Decodes FM radio signals using `rtl_fm` and `redsea`.
- **RDS Decoding**: Captures Program Identification (PI), Program Service (PS), Radio Text (RT), Program Type (PTY), and flags (TMC, TA, TP).
- **Web Interface**:
    - Live view of received RDS messages.
    - Controls for Frequency and RF Gain.
    - "Auto Search" functionality to scan the FM band.
    - Status indicators for traffic flags (TMC, TA, TP).
- **MQTT Support**: Publishes decoded data to an MQTT broker for integration with Home Assistant or other IoT platforms.
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

- `GET /api/status`: Get current tuner status (frequency, gain).
- `POST /api/tune`: Set frequency or gain.
    - Body: `{"frequency": 98.5}` or `{"gain": 40}`
- `POST /api/scan/next`: Scan for the next strong signal.
- `GET /api/messages`: Retrieve recent RDS messages.

## Development

- The backend is written in Python (Flask).
- The frontend uses simple HTML/CSS with HTMX for dynamic updates.
- Data is stored in `data/rds.db` (SQLite).

## License

MIT License
