# CryptoBot Dockerfile
# Python Backend + API Server

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir flask flask-cors

# Copy application code
COPY . .

# Create directories for logs and data if they don't exist
RUN mkdir -p logs data

# Expose the API port
EXPOSE 5000

# Environment variables (override these in docker-compose or at runtime)
ENV BINANCE_US_API_KEY=""
ENV BINANCE_US_API_SECRET=""

# Default command: Start the API server
CMD ["python", "main.py"]
