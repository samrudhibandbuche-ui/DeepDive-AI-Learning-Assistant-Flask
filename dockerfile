FROM python:3.11-slim

# Install FFmpeg
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Render expects the application to listen on this port
EXPOSE 10000

# Start Flask through Gunicorn
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT --timeout 600 app:app"]