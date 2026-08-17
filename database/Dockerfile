# Flyway with the migrations baked in, for running schema changes on RDS.
#
# Compose mounts database/migrations into the stock flyway image instead, so
# editing SQL locally needs no rebuild. On AWS there is nothing to bind-mount:
# the migration job is an ECS task, so the SQL has to travel inside the image.
# Both paths run the identical files, including the
# `CREATE EXTENSION IF NOT EXISTS vector` in V1.
FROM flyway/flyway:10.22.0

COPY migrations /flyway/sql

# FLYWAY_URL, FLYWAY_USER and FLYWAY_PASSWORD are injected from Secrets Manager
# by the ECS task definition.
CMD ["migrate"]
