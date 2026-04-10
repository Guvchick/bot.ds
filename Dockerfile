FROM python:3.11-slim

# Устанавливаем FFmpeg и системные зависимости
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsodium-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Устанавливаем зависимости Python
COPY requirement.txt .
RUN pip install --no-cache-dir -r requirement.txt

# Копируем код бота
COPY . .

# Создаём директории для данных и логов
RUN mkdir -p data logs

CMD ["python", "run.py"]
