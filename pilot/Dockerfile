FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends util-linux poppler-utils tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY pilot/requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt && useradd -u 10001 -m pilot && mkdir -p /data/documents && chown -R pilot:pilot /data
COPY pilot /srv/pilot
COPY deploy/render-start.sh /srv/deploy/render-start.sh
USER pilot
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN python -m pilot.check_tests
CMD ["uvicorn","pilot.api:app","--host","0.0.0.0","--port","8000","--no-access-log","--limit-concurrency","16"]
