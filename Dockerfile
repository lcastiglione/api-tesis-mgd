FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATABASE_PATH=/data/study.sqlite
WORKDIR /app
COPY requirements.txt requirements-analysis.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY calculator ./calculator
COPY VERSION ./VERSION
COPY data/manifest.json ./data/manifest.json
COPY docs ./docs
RUN useradd --uid 10001 --create-home study \
    && mkdir -p /data \
    && chown study:study /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/status',timeout=4)"
ENTRYPOINT ["python","-m","app.entrypoint"]
CMD ["python","-m","app.server"]

FROM runtime AS test
USER root
RUN pip install --no-cache-dir httpx==0.28.1 pytest==9.0.2
COPY tests ./tests
CMD ["python","-m","pytest","-q","-p","no:cacheprovider","tests"]
