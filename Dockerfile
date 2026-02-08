# Multi-stage build for Redsea
FROM python:3.11-slim-bookworm AS builder

# Install build dependencies
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
FROM python:3.11-slim-bookworm

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    rtl-sdr \
    librtlsdr-dev \
    libsndfile1 \
    libliquid1 \
    libjansson4 \
    sox \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy Redsea binary from builder
# Default install prefix with meson might be /usr/local
COPY --from=builder /usr/local/bin/redsea /usr/local/bin/redsea

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port for Web UI
EXPOSE 5000

# Command to run the application
CMD ["python", "-m", "app.main"]
