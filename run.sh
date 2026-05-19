#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
info() { echo -e "${CYAN}[INFO]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }

echo ""
echo "================================================"
echo "  Enterprise RAG + LLMOps Stack"
echo "================================================"
echo ""

CMD="${1:-local}"

# ===========================================================
check_docker() {
  docker --version &>/dev/null || { err "Docker not found. Install Docker Desktop."; return 1; }
  docker info &>/dev/null      || { err "Docker daemon not running. Start Docker Desktop."; return 1; }
  ok "Docker is running"
}

check_gcloud() {
  gcloud --version &>/dev/null || { err "gcloud not found. Install: https://cloud.google.com/sdk/docs/install"; return 1; }
  ok "gcloud available"
}

check_terraform() {
  terraform --version &>/dev/null || { err "terraform not found. Install: https://developer.hashicorp.com/terraform/downloads"; return 1; }
  ok "terraform available"
}

ensure_env() {
  if [[ ! -f .env ]]; then
    info "Creating .env from .env.example..."
    cp .env.example .env
    warn "Please edit .env and set GCP_PROJECT_ID, then re-run."
    exit 1
  fi
  ok ".env exists"
}

wait_healthy() {
  info "Waiting for rag-api health check (up to 90s)..."
  for i in $(seq 1 18); do
    if curl -sf http://localhost:8080/health &>/dev/null; then
      ok "All services healthy (check $i/18)"
      return 0
    fi
    echo "  Waiting... ($i/18) - services starting up"
    sleep 5
  done
  warn "Services took too long. Check logs: ./run.sh logs"
}

print_urls() {
  echo ""
  echo "================================================"
  echo "  Stack is ready!"
  echo "================================================"
  echo ""
  echo "  RAG API:   http://localhost:8080"
  echo "  Docs:      http://localhost:8080/docs"
  echo "  Health:    http://localhost:8080/health"
  echo "  MLflow:    http://localhost:5000"
  echo "  ChromaDB:  http://localhost:8000/api/v1/heartbeat"
  echo ""
  echo "  Quick test:"
  echo "    curl http://localhost:8080/health"
  echo '    curl -X POST http://localhost:8080/rag/query \'
  echo '      -H "Content-Type: application/json" \'
  echo '      -d "{\"query\":\"What is our remote work policy?\",\"strategy\":\"naive\"}"'
  echo ""
  echo "  Commands:"
  echo "    ./run.sh stop      -- stop all local services"
  echo "    ./run.sh destroy   -- stop local + destroy GCP infra"
  echo "    ./run.sh status    -- show container status"
  echo "    ./run.sh logs      -- tail all logs"
  echo ""
}

# ===========================================================
case "$CMD" in

# ------ Local: docker-compose only (no GCP infra cost) -----
local)
  info "MODE: Local dev stack (ChromaDB + Redis + MLflow + RAG API)"
  echo ""
  check_docker
  check_gcloud
  ensure_env

  echo ""
  info "[1/3] Building rag-api image..."
  docker compose -f docker/docker-compose.yml build

  echo ""
  info "[2/3] Starting services..."
  docker compose -f docker/docker-compose.yml up -d

  echo ""
  info "[3/3] Waiting for health checks..."
  wait_healthy
  print_urls
  ;;

# ------ GCP: Terraform + docker-compose --------------------
gcp)
  info "MODE: Full GCP stack (Terraform + local services)"
  echo ""
  check_docker
  check_gcloud
  check_terraform
  ensure_env

  echo ""
  info "[1/4] Checking GCP authentication..."
  gcloud auth application-default print-access-token &>/dev/null \
    || gcloud auth application-default login

  echo ""
  info "[2/4] Provisioning GCP infrastructure with Terraform..."
  cd infra
  terraform init -upgrade
  terraform apply -auto-approve
  cd ..

  echo ""
  info "[3/4] Building and starting local services..."
  docker compose -f docker/docker-compose.yml build
  docker compose -f docker/docker-compose.yml up -d

  echo ""
  info "[4/4] Waiting for health checks..."
  wait_healthy
  print_urls
  ;;

# ------ Stop: docker-compose only --------------------------
stop)
  info "Stopping local docker-compose stack..."
  docker compose -f docker/docker-compose.yml down
  ok "Local services stopped. GCP infra is still running (use 'destroy' to remove it)."
  ;;

# ------ Destroy: everything --------------------------------
destroy)
  warn "This will stop local services AND destroy all GCP Terraform infrastructure."
  warn "BigQuery tables, GCS buckets, and Vertex AI indexes will be deleted."
  echo ""
  read -r -p "Type YES to confirm: " CONFIRM
  [[ "$CONFIRM" == "YES" ]] || { info "Aborted."; exit 0; }

  echo ""
  info "[1/2] Stopping docker-compose..."
  docker compose -f docker/docker-compose.yml down -v || true

  echo ""
  info "[2/2] Destroying Terraform GCP infrastructure..."
  cd infra
  terraform destroy -auto-approve
  cd ..
  ok "Destroyed."
  ;;

# ------ Status ---------------------------------------------
status)
  info "Docker containers:"
  docker compose -f docker/docker-compose.yml ps
  echo ""
  info "Health checks:"
  curl -sf http://localhost:8080/health  && echo "  rag-api:  healthy" || echo "  rag-api:  not reachable"
  curl -sf http://localhost:5000/health  && echo "  mlflow:   healthy" || echo "  mlflow:   not reachable"
  curl -sf http://localhost:8000/api/v1/heartbeat && echo "  chromadb: healthy" || echo "  chromadb: not reachable"
  ;;

# ------ Logs -----------------------------------------------
logs)
  SVC="${2:-}"
  if [[ -z "$SVC" ]]; then
    docker compose -f docker/docker-compose.yml logs -f
  else
    docker compose -f docker/docker-compose.yml logs -f "$SVC"
  fi
  ;;

# ------ Help -----------------------------------------------
help|--help|-h)
  echo "USAGE:  ./run.sh [command]"
  echo ""
  echo "COMMANDS:"
  echo "  local     Start local dev stack (Docker only, no GCP cost)   [default]"
  echo "  gcp       Provision GCP infra with Terraform + start local stack"
  echo "  stop      Stop local docker-compose services"
  echo "  destroy   Stop local services AND destroy all GCP Terraform infra"
  echo "  status    Show running containers + health checks"
  echo "  logs      Tail all service logs"
  echo "  logs <svc> Tail a specific service (rag-api, mlflow, redis, chromadb)"
  echo ""
  echo "EXAMPLES:"
  echo "  ./run.sh               # start local dev"
  echo "  ./run.sh gcp           # full GCP stack"
  echo "  ./run.sh stop          # stop local services"
  echo "  ./run.sh logs rag-api  # tail rag-api logs"
  echo "  ./run.sh destroy       # tear everything down"
  echo ""
  ;;

*)
  err "Unknown command: $CMD"
  echo "Run './run.sh help' for usage."
  exit 1
  ;;
esac
