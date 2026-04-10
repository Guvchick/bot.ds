FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsodium-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirement.txt .
RUN pip install --no-cache-dir -r requirement.txt

COPY . .

RUN mkdir -p logs

CMD ["python", "run.py"]
