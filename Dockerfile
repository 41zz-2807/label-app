FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PORT=8010 \
    DB_PATH=/app/data/labels.db

WORKDIR /app

COPY static ./static
COPY fetch_vendor.py .
RUN python fetch_vendor.py

COPY server.py .
RUN mkdir -p /app/data

EXPOSE 8010
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT','8010'),timeout=3)"

CMD ["python", "server.py"]
