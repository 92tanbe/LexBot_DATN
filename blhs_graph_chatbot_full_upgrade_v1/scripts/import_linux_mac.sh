#!/usr/bin/env bash
set -euo pipefail
RESET="${1:-}"
CONTAINER="blhs-neo4j-full-upgrade"
USER="neo4j"
PASS="password123456"

docker compose up -d neo4j
for i in {1..60}; do
  if docker exec "$CONTAINER" cypher-shell -u "$USER" -p "$PASS" "RETURN 1;" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
if [[ "$RESET" == "--reset" ]]; then
  docker exec "$CONTAINER" cypher-shell -u "$USER" -p "$PASS" -f /cypher/00_reset_database.cypher
fi
docker exec "$CONTAINER" cypher-shell -u "$USER" -p "$PASS" -f /cypher/01_constraints_indexes.cypher
docker exec "$CONTAINER" cypher-shell -u "$USER" -p "$PASS" -f /cypher/02_import_csv.cypher
docker exec "$CONTAINER" cypher-shell -u "$USER" -p "$PASS" -f /cypher/03_verify_import.cypher
