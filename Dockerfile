FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure log directory exists for RotatingFileHandler.
RUN mkdir -p logs

ENV PORT=5001 \
    WORKERS=2 \
    TIMEOUT=120

EXPOSE 5001

# Use callable syntax for the factory instead of --factory (not available here).
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8080","--workers","2"]
