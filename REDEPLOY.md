# RAG Project — Redeploy Guide

All GCP resources were deleted on 2026-05-20 to save costs. Use this guide to bring everything back.

**Total time: ~20–30 minutes**

---

## Prerequisites

- `gcloud` authenticated: `gcloud auth login`
- `kubectl` installed
- `helm` installed
- `terraform` installed
- New Gemini API key from https://aistudio.google.com/app/apikey
- New GitHub PAT from https://github.com/settings/tokens (repo + workflow scopes)

---

## Step 1 — Recreate GCP infrastructure (~5–10 min)

```powershell
cd infra
terraform init
terraform apply -auto-approve
```

Creates: GKE cluster, Redis Memorystore, GCS buckets, Artifact Registry, IAM service accounts, Workload Identity Federation.

After apply, note the outputs (Redis IP, cluster name, etc.):
```powershell
terraform output
```

---

## Step 2 — Connect kubectl

```powershell
gcloud container clusters get-credentials rag-cluster --zone=us-central1-a --project=llmops-495904
```

---

## Step 3 — Recreate Kubernetes secrets

```powershell
kubectl create secret generic rag-config `
  --from-literal=gemini_api_key=YOUR_NEW_GEMINI_KEY `
  --from-literal=redis_host=<redis-ip-from-terraform-output> `
  --from-literal=gcp_project_id=llmops-495904 `
  --from-literal=gcs_processed_bucket=llmops-495904-rag-processed `
  --from-literal=vector_search_index_id="" `
  --from-literal=vector_search_endpoint_id=""
```

---

## Step 4 — Deploy ChromaDB and MLflow

```powershell
kubectl apply -f k8s/chromadb.yaml
kubectl apply -f k8s/mlflow.yaml
```

Wait for pods to be ready:
```powershell
kubectl get pods -w
```

---

## Step 5 — Build and push the RAG API image (~10 min)

```powershell
gcloud builds submit --tag us-central1-docker.pkg.dev/llmops-495904/rag-repo/rag-api:latest .
```

---

## Step 6 — Deploy RAG API via Helm

```powershell
helm upgrade --install rag-api helm/rag-api `
  --set image.repository=us-central1-docker.pkg.dev/llmops-495904/rag-repo/rag-api `
  --set image.tag=latest
```

---

## Step 7 — Re-add GitHub Secrets (for CI/CD auto-deploy)

Go to https://github.com/kkDapp/llmops/settings/secrets/actions and add:

| Secret | Value |
|--------|-------|
| `GEMINI_API_KEY` | New key from Google AI Studio |
| `GCP_PROJECT_ID` | `llmops-495904` |

---

## Step 8 — Re-ingest documents

Upload PDFs via the RAG UI — the pipeline will re-index them into ChromaDB automatically.

---

## Get the public URLs after deploy

```powershell
kubectl get svc
```

Look for the `EXTERNAL-IP` values for:
- `rag-api-rag-api` — RAG UI
- `mlflow` — MLflow tracking UI
- `prometheus-grafana` — Grafana dashboards
