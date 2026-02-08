# Multi-stage build for Redsea
FROM python:3.11-slim-bookworm AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    automake \
    libtool \
    libsndfile1-dev \
    libliquid-dev \
    libjansson-dev \
    && rm -rf /var/lib/apt/lists/*

# Clone and build Redsea
WORKDIR /build
RUN git clone https://github.com/windytan/redsea.git
WORKDIR /build/redsea
RUN ./autogen.sh && ./configure && make && make install

# Final image
FROM python:3.11-slim-bookworm

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    rtl-sdr \
    librtlsdr-dev \
    libsndfile1 \
    libliquid1 \
    libjansson4 \
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

# Expose port for Web UI
EXPOSE 5000

# Command to run the application
CMD ["python", "app/main.py"]
