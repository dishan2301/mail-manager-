#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")"
container=oeis-docker-test
backup="${container}-before-dashboard-$(date +%Y%m%d%H%M%S)"
env_file=$(mktemp)
chmod 600 "$env_file"
trap 'rm -f "$env_file"' EXIT

# Preserve the current container settings without printing secrets.
docker inspect "$container" --format '{{range .Config.Env}}{{println .}}{{end}}' > "$env_file"
docker build -t oeis:local .
docker stop "$container"
docker rename "$container" "$backup"

if ! docker run -d --name "$container" \
  -p 127.0.0.1:10002:8000 \
  -p 192.168.1.36:10002:8000 \
  -v oeis-test-data:/data \
  --env-file "$env_file" \
  -e GRAPH_REDIRECT_URI=http://localhost:10002/api/graph/oauth/callback \
  -e FRONTEND_URL=http://localhost:10002 \
  -e DASHBOARD_URL=http://192.168.1.36:10002 \
  -e ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.36 \
  -e SCHEDULER_ENABLED=true \
  -e SYNC_INTERVAL_SECONDS=60 \
  oeis:local; then
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker rename "$backup" "$container"
  docker start "$container"
  exit 1
fi

for attempt in $(seq 1 45); do
  if docker exec "$container" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=2)" >/dev/null 2>&1; then
    echo "Docker app ready at http://localhost:10002"
    echo "Previous container kept as $backup"
    exit 0
  fi
  sleep 2
done

docker logs --tail 30 "$container" >&2
docker rm -f "$container"
docker rename "$backup" "$container"
docker start "$container"
echo "New container failed health check; restored previous container." >&2
exit 1
