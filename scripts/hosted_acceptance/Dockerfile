# Disposable acceptance runtime, not a production deployment image.
FROM python:3.10-slim-bookworm
RUN pip install --no-cache-dir fastapi==0.142.3 uvicorn==0.54.0 cryptography==50.0.2 PyJWT==2.15.1 requests==2.34.2 tink==1.16.1 \
    && useradd --uid 10001 --create-home runtime \
    && mkdir /data && chown runtime:runtime /data
COPY hub/orion_hub /app/hub/orion_hub
COPY issuer.py /app/issuer.py
COPY worker.py /app/worker.py
COPY acceptance.py /app/acceptance.py
COPY src/orion_mini /app/src/orion_mini
ENV PYTHONPATH=/app/hub:/app/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
WORKDIR /app
CMD ["python", "-m", "orion_hub.hosted_server"]
