#!/usr/bin/env bash
# scripts/manage.sh — server management for bivd-url-shortener
#
# Setup: copy scripts/.env.local.example → scripts/.env.local and fill in values.
# Usage: ./scripts/manage.sh <command> [options]
#
# Requires: ssh/scp (key-based), or sshpass (password-based: brew install sshpass)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load local config (never committed)
if [ -f "$SCRIPT_DIR/.env.local" ]; then
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/.env.local"
fi

DROPLET_HOST="${DROPLET_HOST:?Set DROPLET_HOST in scripts/.env.local}"
DROPLET_USER="${DROPLET_USER:-root}"
DROPLET_PASS="${DROPLET_PASS:-}"          # Leave empty to use SSH key auth
DEPLOY_DIR="${DEPLOY_DIR:-/opt/urlshortener}"
DISCORD_WEBHOOK="${DISCORD_WEBHOOK:-}"
COMPOSE_FILE="docker-compose.1gb.yml"

# ── SSH / SCP wrappers (supports both password and key auth) ──────────────────

_ssh() {
    if [ -n "$DROPLET_PASS" ]; then
        sshpass -p "$DROPLET_PASS" ssh \
            -o StrictHostKeyChecking=accept-new \
            -o ConnectTimeout=10 \
            "$DROPLET_USER@$DROPLET_HOST" "$@"
    else
        ssh \
            -o StrictHostKeyChecking=accept-new \
            -o ConnectTimeout=10 \
            "$DROPLET_USER@$DROPLET_HOST" "$@"
    fi
}

_scp() {
    if [ -n "$DROPLET_PASS" ]; then
        sshpass -p "$DROPLET_PASS" scp \
            -o StrictHostKeyChecking=accept-new "$@"
    else
        scp -o StrictHostKeyChecking=accept-new "$@"
    fi
}

# ── Commands ──────────────────────────────────────────────────────────────────

cmd_setup() {
    echo ">>> One-time server setup on $DROPLET_HOST"
    _ssh bash << 'REMOTE'
        set -euo pipefail
        apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
            curl git docker.io docker-compose-plugin sshpass

        systemctl enable docker
        systemctl start docker

        mkdir -p /opt/urlshortener
        echo "Setup complete."
REMOTE
    echo "Done."
}

cmd_upload_seeds() {
    echo ">>> Checking CSV files..."
    local missing=0
    for f in users.csv urls.csv events.csv; do
        if [ ! -f "$PROJECT_DIR/$f" ]; then
            echo "  MISSING: $f"
            missing=1
        else
            echo "  OK: $f ($(wc -l < "$PROJECT_DIR/$f") rows)"
        fi
    done

    if [ "$missing" -eq 1 ]; then
        echo "ERROR: generate the missing CSV files first, then retry."
        exit 1
    fi

    echo ">>> Uploading CSV files to $DROPLET_HOST:$DEPLOY_DIR ..."
    _scp \
        "$PROJECT_DIR/users.csv" \
        "$PROJECT_DIR/urls.csv" \
        "$PROJECT_DIR/events.csv" \
        "$DROPLET_USER@$DROPLET_HOST:$DEPLOY_DIR/"
    echo "Done. Run './scripts/manage.sh reseed csv' to seed with these files."
}

cmd_reseed() {
    local mode="${1:-csv}"   # csv | faker
    echo ">>> Reseeding database on $DROPLET_HOST (mode: $mode)"

    _ssh bash << REMOTE
        set -euo pipefail
        cd "$DEPLOY_DIR"

        echo "Terminating active DB connections..."
        docker compose -f "$COMPOSE_FILE" exec -T db psql -U postgres -c \
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='hackathon_db' AND pid <> pg_backend_pid();" \
            2>/dev/null || true

        echo "Dropping and recreating database..."
        docker compose -f "$COMPOSE_FILE" exec -T db psql -U postgres -c \
            "DROP DATABASE IF EXISTS hackathon_db;"
        docker compose -f "$COMPOSE_FILE" exec -T db psql -U postgres -c \
            "CREATE DATABASE hackathon_db;"

        if [ "$mode" = "faker" ]; then
            echo "Removing CSV files so Faker generates fresh data..."
            rm -f "$DEPLOY_DIR/users.csv" "$DEPLOY_DIR/urls.csv" "$DEPLOY_DIR/events.csv"
        else
            echo "CSV files will be used if present."
        fi

        echo "Restarting app to trigger seeding..."
        docker compose -f "$COMPOSE_FILE" restart app

        echo ""
        echo "Seeding in progress. Check logs:"
        echo "  docker compose -f $COMPOSE_FILE logs -f app"
REMOTE
    echo "Done."
}

cmd_status() {
    echo ""
    echo "══════════════════════════════════════════════"
    printf "  Server Status: %s\n" "$DROPLET_HOST"
    echo "══════════════════════════════════════════════"

    _ssh bash << REMOTE
        echo ""
        echo "── Docker containers ──────────────────────"
        docker compose -f "$DEPLOY_DIR/$COMPOSE_FILE" ps 2>/dev/null || echo "(no containers running)"
        echo ""
        echo "── Memory ─────────────────────────────────"
        free -h
        echo ""
        echo "── Disk ────────────────────────────────────"
        df -h /
        echo ""
        echo "── Load average ────────────────────────────"
        uptime
        echo ""
        echo "── Health check ────────────────────────────"
        curl -sf --max-time 5 http://localhost/health 2>/dev/null && echo "" || echo "FAILED (app may be down)"
REMOTE
}

cmd_notify() {
    if [ -z "$DISCORD_WEBHOOK" ]; then
        echo "DISCORD_WEBHOOK not set in scripts/.env.local — skipping."
        return 0
    fi

    echo ">>> Fetching server status for Discord..."

    local raw_status app_status mem disk color emoji
    raw_status=$(_ssh "curl -sf --max-time 5 http://localhost/health" 2>/dev/null \
        || echo '{"status":"down","checks":{}}')
    app_status=$(echo "$raw_status" | \
        python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" \
        2>/dev/null || echo "unknown")
    mem=$(_ssh "free -m | awk 'NR==2{printf \"%s / %s MB (%.0f%%)\", \$3, \$2, \$3*100/\$2}'")
    disk=$(_ssh "df -h / | awk 'NR==2{printf \"%s used of %s\", \$3, \$2}'")

    if [ "$app_status" = "ok" ]; then
        color=3066993   # green
        emoji=":white_check_mark:"
    else
        color=15158332  # red
        emoji=":red_circle:"
    fi

    local timestamp
    timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    local payload
    payload=$(cat << EOF
{
  "embeds": [{
    "title": "${emoji} URL Shortener — Server Status",
    "color": ${color},
    "fields": [
      {"name": "App Status", "value": "${app_status}", "inline": true},
      {"name": "Host",       "value": "${DROPLET_HOST}", "inline": true},
      {"name": "Memory",     "value": "${mem}", "inline": false},
      {"name": "Disk",       "value": "${disk}", "inline": false}
    ],
    "footer": {"text": "bivd-url-shortener"},
    "timestamp": "${timestamp}"
  }]
}
EOF
)

    curl -s -X POST \
        -H "Content-Type: application/json" \
        -d "$payload" \
        "$DISCORD_WEBHOOK" > /dev/null
    echo "Discord notification sent."
}

cmd_logs() {
    local service="${1:-app}"
    echo ">>> Tailing logs for service: $service"
    _ssh "cd $DEPLOY_DIR && docker compose -f $COMPOSE_FILE logs --tail=100 -f $service"
}

cmd_ping() {
    echo ">>> Pinging $DROPLET_HOST ..."
    _ssh "echo 'SSH OK' && docker compose -f $DEPLOY_DIR/$COMPOSE_FILE ps --quiet | wc -l | xargs echo 'Running containers:'"
}

# ── Help ──────────────────────────────────────────────────────────────────────

cmd_help() {
    cat << 'HELP'
Usage: ./scripts/manage.sh <command> [options]

Commands:
  setup                 One-time: apt-get update + install Docker on a fresh droplet
  upload-seeds          SCP users.csv, urls.csv, events.csv to the server
  reseed [csv|faker]    Drop DB and reseed (csv=use uploaded files, faker=generate fresh)
  status                Show containers, memory, disk, and health check
  notify                Post a status embed to Discord webhook
  logs [service]        Tail container logs (default: app)
  ping                  Quick SSH connectivity + container count check

Config — create scripts/.env.local (gitignored):
  DROPLET_HOST=1.2.3.4              droplet public IP
  DROPLET_USER=root                 SSH username
  DROPLET_PASS=                     SSH password (leave empty to use key auth)
  DEPLOY_DIR=/opt/urlshortener      deployment directory on server
  DISCORD_WEBHOOK=https://...       Discord webhook URL for notifications

Key vs password auth:
  Key auth (default): ssh-copy-id root@<droplet-ip>, leave DROPLET_PASS empty
  Password auth:      set DROPLET_PASS, requires: brew install sshpass (Mac)
HELP
}

# ── Dispatch ──────────────────────────────────────────────────────────────────

case "${1:-help}" in
    setup)          cmd_setup ;;
    upload-seeds)   cmd_upload_seeds ;;
    reseed)         cmd_reseed "${2:-csv}" ;;
    status)         cmd_status ;;
    notify)         cmd_notify ;;
    logs)           cmd_logs "${2:-app}" ;;
    ping)           cmd_ping ;;
    help|*)         cmd_help ;;
esac
