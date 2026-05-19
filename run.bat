@echo off
setlocal enabledelayedexpansion
title RAG Project Launcher

echo.
echo ================================================
echo   Enterprise RAG + LLMOps Stack
echo ================================================
echo.

set CMD=%1
if "%CMD%"=="" set CMD=local
if /i "%CMD%"=="help"    goto :usage
if /i "%CMD%"=="--help"  goto :usage
if /i "%CMD%"=="-h"      goto :usage
if /i "%CMD%"=="local"   goto :local
if /i "%CMD%"=="gcp"     goto :gcp
if /i "%CMD%"=="stop"    goto :stop
if /i "%CMD%"=="destroy" goto :destroy
if /i "%CMD%"=="status"  goto :status
if /i "%CMD%"=="logs"    goto :logs

echo ERROR: Unknown command "%CMD%"
goto :usage

:: ===========================================================
:local
echo [MODE] Local dev stack (ChromaDB + Redis + MLflow + RAG API)
echo.

:: --- Check Docker ---
docker --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker not found. Install Docker Desktop.
  exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker daemon is not running. Start Docker Desktop first.
  exit /b 1
)
echo [OK] Docker is running

:: --- Ensure .env exists ---
if not exist .env (
  echo [INFO] .env not found - creating from .env.example...
  copy .env.example .env >nul
  echo [WARN] Edit .env and set GCP_PROJECT_ID, then re-run.
  notepad .env
  exit /b 1
)
echo [OK] .env found

:: --- Build image ---
echo.
echo [1/3] Building rag-api image (first run takes 3-5 min)...
docker compose -f docker/docker-compose.yml build
if errorlevel 1 (
  echo ERROR: Docker build failed. Run ".\run logs rag-api" for details.
  exit /b 1
)
echo [OK] Build complete

:: --- Start services ---
echo.
echo [2/3] Starting all services...
docker compose -f docker/docker-compose.yml up -d
if errorlevel 1 (
  echo ERROR: docker compose up failed.
  exit /b 1
)
echo [OK] Services started

:: --- Wait for health ---
echo.
echo [3/3] Waiting for rag-api to be ready (up to 90s)...
call :wait_healthy

goto :print_urls

:: ===========================================================
:gcp
echo [MODE] Full GCP stack (Terraform + local services)
echo.

:: --- Check Docker ---
docker --version >nul 2>&1
if errorlevel 1 (echo ERROR: Docker not found. & exit /b 1)
docker info >nul 2>&1
if errorlevel 1 (echo ERROR: Docker daemon not running. & exit /b 1)
echo [OK] Docker is running

:: --- Check gcloud ---
gcloud --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: gcloud not found. Install: https://cloud.google.com/sdk/docs/install
  exit /b 1
)
echo [OK] gcloud available

:: --- Check Terraform ---
terraform --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: terraform not found. Install: https://developer.hashicorp.com/terraform/downloads
  exit /b 1
)
echo [OK] terraform available

:: --- Ensure .env ---
if not exist .env (
  copy .env.example .env >nul
  echo [WARN] Edit .env with your GCP_PROJECT_ID then re-run.
  notepad .env
  exit /b 1
)
echo [OK] .env found

echo.
echo [1/4] Checking GCP auth...
gcloud auth application-default print-access-token >nul 2>&1
if errorlevel 1 (
  echo Logging in to GCP...
  gcloud auth application-default login
)
echo [OK] GCP authenticated

echo.
echo [2/4] Running Terraform (provisions GCP infra)...
cd infra
terraform init -upgrade
if errorlevel 1 (echo ERROR: terraform init failed. & cd .. & exit /b 1)
terraform apply -auto-approve
if errorlevel 1 (echo ERROR: terraform apply failed. & cd .. & exit /b 1)
cd ..
echo [OK] GCP infrastructure provisioned

echo.
echo [3/4] Building and starting local services...
docker compose -f docker/docker-compose.yml build
if errorlevel 1 (echo ERROR: Docker build failed. & exit /b 1)
docker compose -f docker/docker-compose.yml up -d
if errorlevel 1 (echo ERROR: docker compose up failed. & exit /b 1)
echo [OK] Services started

echo.
echo [4/4] Waiting for rag-api health check...
call :wait_healthy

goto :print_urls

:: ===========================================================
:stop
echo [STOP] Stopping local docker-compose stack...
docker compose -f docker/docker-compose.yml down
echo Done. (GCP infra still running - use ".\run destroy" to remove it)
goto :eof

:: ===========================================================
:destroy
echo [DESTROY] This will stop all containers AND destroy GCP infrastructure.
echo           This deletes BigQuery tables, GCS data, Vertex AI indexes.
echo.
set /p CONFIRM=Type YES to confirm:
if not "%CONFIRM%"=="YES" (echo Aborted. & goto :eof)
echo.
echo [1/2] Stopping docker-compose...
docker compose -f docker/docker-compose.yml down -v
echo.
echo [2/2] Destroying Terraform GCP infra...
cd infra
terraform destroy -auto-approve
cd ..
echo [OK] Everything destroyed.
goto :eof

:: ===========================================================
:status
echo [STATUS] Running containers:
docker compose -f docker/docker-compose.yml ps
echo.
echo [STATUS] Health checks:
curl -sf http://localhost:8080/health >nul 2>&1
if errorlevel 1 (echo   rag-api  : NOT reachable) else (echo   rag-api  : healthy - http://localhost:8080)
curl -sf http://localhost:5000/health >nul 2>&1
if errorlevel 1 (echo   mlflow   : NOT reachable) else (echo   mlflow   : healthy - http://localhost:5000)
curl -sf http://localhost:8000/api/v1/heartbeat >nul 2>&1
if errorlevel 1 (echo   chromadb : NOT reachable) else (echo   chromadb : healthy - http://localhost:8000)
redis-cli -h localhost ping >nul 2>&1
if errorlevel 1 (echo   redis    : NOT reachable) else (echo   redis    : healthy - localhost:6379)
goto :eof

:: ===========================================================
:logs
set SVC=%2
if "%SVC%"=="" (
  docker compose -f docker/docker-compose.yml logs -f
) else (
  docker compose -f docker/docker-compose.yml logs -f %SVC%
)
goto :eof

:: ===========================================================
:wait_healthy
set /a TRIES=0
:health_loop
set /a TRIES+=1
if %TRIES% GTR 18 (
  echo [WARN] rag-api health check timed out. Check logs: .\run logs rag-api
  goto :eof
)
curl -sf http://localhost:8080/health >nul 2>&1
if not errorlevel 1 (
  echo [OK] Stack is healthy after %TRIES% checks.
  goto :eof
)
echo   Checking... attempt %TRIES%/18
timeout /t 5 /nobreak >nul
goto :health_loop

:: ===========================================================
:print_urls
echo.
echo ================================================
echo   Stack is ready!
echo ================================================
echo.
echo   RAG API   : http://localhost:8080
echo   API Docs  : http://localhost:8080/docs
echo   Health    : http://localhost:8080/health
echo   MLflow UI : http://localhost:5000
echo   ChromaDB  : http://localhost:8000/api/v1/heartbeat
echo.
echo   Quick test:
echo     curl http://localhost:8080/health
echo.
echo   Ingest a document:
echo     curl -X POST http://localhost:8080/ingest/upload ...
echo.
echo   Query (all 5 strategies: naive/advanced/hybrid/graph/agentic):
echo     curl -X POST http://localhost:8080/rag/query ^
echo       -H "Content-Type: application/json" ^
echo       -d "{\"query\":\"What is our remote work policy?\",\"strategy\":\"naive\"}"
echo.
echo   Manage:
echo     .\run status        check service health
echo     .\run logs          tail all logs
echo     .\run logs rag-api  tail rag-api only
echo     .\run stop          stop all services
echo.
goto :eof

:: ===========================================================
:usage
echo.
echo USAGE:  .\run [command]
echo.
echo COMMANDS:
echo   local     Start local dev stack - Docker only, no GCP cost  [default]
echo   gcp       Provision GCP infra with Terraform + start local stack
echo   stop      Stop all local containers
echo   destroy   Stop containers + destroy all GCP Terraform infra
echo   status    Show container status + health checks
echo   logs      Tail all service logs  (Ctrl+C to stop)
echo   logs ^<n^>  Tail one service:  rag-api  mlflow  redis  chromadb
echo.
echo EXAMPLES:
echo   .\run                  start local dev stack
echo   .\run gcp              full GCP provisioning + local stack
echo   .\run status           health check all services
echo   .\run logs rag-api     tail rag-api logs
echo   .\run stop             stop everything
echo   .\run destroy          nuclear option - removes all infra
echo.
goto :eof
