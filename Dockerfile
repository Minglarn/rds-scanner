# Multi-stage build for Redsea
FROM python:3.11-bookworm AS builder

# Install build dependencies for Redsea
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    meson \
    ninja-build \
    libsndfile1-dev \
    libliquid-dev \
    libjansson-dev \
    && rm -rf /var/lib/apt/lists/*

# Clone and build Redsea
WORKDIR /build
RUN git clone https://github.com/windytan/redsea.git
WORKDIR /build/redsea
RUN meson setup build && meson compile -C build && meson install -C build

# Final image
FROM python:3.11-bookworm

# Install runtime dependencies (FM + DAB)
# welle.io includes welle-cli for headless DAB reception
RUN apt-get update && apt-get install -y \
    rtl-sdr \
    librtlsdr0 \
    libsndfile1 \
    libliquid1 \
    libjansson4 \
    sox \
    ffmpeg \
    welle.io \
    soapysdr-module-rtlsdr \
    && rm -rf /var/lib/apt/lists/*

# Copy Redsea binary from builder
COPY --from=builder /usr/local/bin/redsea /usr/local/bin/redsea

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose ports: 5000 (Flask), 7979 (welle-cli web)
EXPOSE 5000 7979

# Command to run the application
CMD ["python", "-m", "app.main"]
