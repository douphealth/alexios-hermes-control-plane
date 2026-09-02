FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /var/lib/ahcp/backups \
    && chown -R appuser:appuser /var/lib/ahcp
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install .
USER appuser
CMD ["ahcp-api"]
