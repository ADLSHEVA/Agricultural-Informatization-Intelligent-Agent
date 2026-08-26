FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8080

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY origin ./origin
COPY rules ./rules

RUN useradd --create-home --uid 10001 origin \
    && mkdir -p /app/data \
    && chown -R origin:origin /app
USER origin

CMD ["sh", "-c", "uvicorn origin.main:app --host 0.0.0.0 --port ${PORT}"]
