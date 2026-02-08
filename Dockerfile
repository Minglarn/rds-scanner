# Multi-stage build for Redsea and Welle-cli (DAB)
FROM python:3.11-slim-bookworm AS builder

# Install build dependencies for Redsea + Welle-cli
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    meson \
    ninja-build \
    cmake \
    libsndfile1-dev \
    libliquid-dev \
    libjansson-dev \
    librtlsdr-dev \
    libfftw3-dev \
    libfaad-dev \
    libmpg123-dev \
    && rm -rf /var/lib/apt/lists/*

# Clone and build Redsea
WORKDIR /build
RUN git clone https://github.com/windytan/redsea.git
WORKDIR /build/redsea
RUN meson setup build && meson compile -C build && meson install -C build

# Clone and build Welle-cli (headless DAB decoder)
WORKDIR /build
RUN git clone https://github.com/AlbrechtL/welle.io.git
WORKDIR /build/welle.io
RUN mkdir build && cd build && \
    cmake .. -DRTLSDR=1 -DBUILD_WELLE_IO=OFF -DBUILD_WELLE_CLI=ON && \
    make -j$(nproc) && \
    cp welle-cli /usr/local/bin/

# Final image
FROM python:3.11-slim-bookworm

# Install runtime dependencies (FM + DAB)
# Note: libfaad2 may require non-free repo on some systems
RUN apt-get update && apt-get install -y --no-install-recommends \
    rtl-sdr \
    librtlsdr0 \
    libsndfile1 \
    libliquid2 \
    libjansson4 \
    libfftw3-single3 \
    libmpg123-0 \
    sox \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy binaries from builder
COPY --from=builder /usr/local/bin/redsea /usr/local/bin/redsea
COPY --from=builder /usr/local/bin/welle-cli /usr/local/bin/welle-cli

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
