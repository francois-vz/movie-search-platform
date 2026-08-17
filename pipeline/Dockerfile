FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Source is required at install time because the project is installed from
# pyproject (declared packages: src, src.pipeline).
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

# Reports are written here; also bind-mounted from the host via docker-compose.
RUN mkdir -p /app/reports

# Runs the pipeline once and exits.
CMD ["python", "-m", "src.main"]
