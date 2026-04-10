FROM python:3.11-slim

# Системные зависимости: FFmpeg, libsodium (PyNaCl), libpq (asyncpg)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsodium-dev \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirement.txt .
RUN pip install --no-cache-dir -r requirement.txt

COPY . .

RUN mkdir -p logs

CMD ["python", "run.py"]
