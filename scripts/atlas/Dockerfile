FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ATLAS_EXPORT_PATH=/data/movies.parquet \
    ATLAS_WAIT=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data

COPY scripts/atlas/requirements.txt /app/scripts/atlas/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/scripts/atlas/requirements.txt

COPY scripts/export_embeddings_atlas.py /app/scripts/export_embeddings_atlas.py
COPY database/queries/atlas_export.sql /app/database/queries/atlas_export.sql
# Imported by the CLI via `--with atlas_color_by`; the entrypoint puts this
# directory on PYTHONPATH. See the module for why the colour-by column cannot be
# passed as a CLI option.
COPY scripts/atlas/atlas_color_by.py /app/scripts/atlas/atlas_color_by.py
COPY scripts/atlas/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 7000

ENTRYPOINT ["/app/entrypoint.sh"]
