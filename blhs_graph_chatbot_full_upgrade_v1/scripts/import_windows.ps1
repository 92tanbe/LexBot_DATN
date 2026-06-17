param(
  [switch]$Reset
)
$ErrorActionPreference = "Stop"
$Container = "blhs-neo4j-full-upgrade"
$User = "neo4j"
$Pass = "password123456"

Write-Host "Starting Neo4j..."
docker compose up -d neo4j

Write-Host "Waiting for Neo4j Bolt..."
for ($i=0; $i -lt 60; $i++) {
  try {
    docker exec $Container cypher-shell -u $User -p $Pass "RETURN 1;" | Out-Null
    break
  } catch {
    Start-Sleep -Seconds 2
  }
}

if ($Reset) {
  Write-Host "Reset database..."
  docker exec $Container cypher-shell -u $User -p $Pass -f /cypher/00_reset_database.cypher
}

Write-Host "Create constraints and indexes..."
docker exec $Container cypher-shell -u $User -p $Pass -f /cypher/01_constraints_indexes.cypher

Write-Host "Import CSV..."
docker exec $Container cypher-shell -u $User -p $Pass -f /cypher/02_import_csv.cypher

Write-Host "Verify import..."
docker exec $Container cypher-shell -u $User -p $Pass -f /cypher/03_verify_import.cypher

Write-Host "Done. Open http://localhost:7474 with neo4j / password123456"
