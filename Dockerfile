FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app

RUN apt-get update && apt-get install -y gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8005
CMD ["sh", "-c", "python -c 'import api.main; print(\"Import OK\")' 2>&1 && uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8005} --workers 2"]
