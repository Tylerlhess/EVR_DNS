# Use Python base image
FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    bind9 \
    bind9utils \
    dnsutils \
    && rm -rf /var/lib/apt/lists/*

# Install IPFS
# RUN wget https://dist.ipfs.io/go-ipfs/v0.12.0/go-ipfs_v0.12.0_linux-amd64.tar.gz \
#     && tar xvfz go-ipfs_v0.12.0_linux-amd64.tar.gz \
#     && cd go-ipfs \
#     && bash install.sh \
#     && cd .. \
#     && rm -rf go-ipfs*

# Create app directory and logs directory
WORKDIR /app
RUN mkdir -p /app/logs
RUN mkdir -p /etc/bind/zones

# Configure BIND
COPY named.conf.local /etc/bind/
COPY named.conf.options /etc/bind/
COPY zones/db.badguyty.com /etc/bind/zones/

# Set proper permissions for BIND
RUN chown -R bind:bind /etc/bind/zones && \
    chmod -R 755 /etc/bind/zones

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

COPY config.env .
# RUN source config.env
# Copy application code
COPY dnsserver.py .

# Initialize IPFS
# RUN ipfs init

# Create volumes for IPFS data, logs, and BIND data
VOLUME ["/root/.ipfs", "/app/logs", "/etc/bind", "/var/cache/bind", "/var/lib/bind"]

# Expose IPFS and DNS ports
EXPOSE 4001 5001 8080 53/udp 53/tcp

# Create startup script
RUN echo '#!/bin/bash\n\
source config.env\n\
# Start BIND9\n\
named -g &\n\
\n\
# Start IPFS daemon\n\
# ipfs daemon --enable-gc &\n\
\n\
# Wait for services to start\n\
sleep 5\n\
\n\
# Start DNS watcher\n\
python dnsserver.py > /app/logs/dns_server.log 2>&1\n\
' > /app/start.sh && chmod +x /app/start.sh

# Set entrypoint
ENTRYPOINT ["/app/start.sh"] 