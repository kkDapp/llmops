# Enterprise Multi-RAG + LLMOps on GCP — End-to-End Project Guide

## What you will build

An enterprise-scale RAG system with **5 retrieval strategies** + a **full LLMOps improvement pipeline**
running on Google Cloud Platform. The system answers questions from documents AND continuously
improves itself through automated evaluation, drift detection, and fine-tuning feedback loops.

```
                     ┌─────────────────────────────────────────────┐
                     │               GCP CLOUD                      │
                     │                                             │
  PDF/DOCX/HTML ──►  │  GCS Bucket ──► Pub/Sub ──► Worker         │
                     │                               │             │
                     │                    Document AI (OCR)         │
                     │                    Vertex AI Embeddings      │
                     │                    Vertex AI Vector Search   │
                     │                               │             │
                     │  ┌────────────────────────────┘             │
                     │  │   RAG API (GKE — 2–20 pods)              │
                     │  │                                          │
                     │  │  POST /rag/query?strategy=hybrid          │
                     │  │    ├── naive    → top-k vector search     │
                     │  │    ├── advanced → HyDE + rerank + compress│
                     │  │    ├── hybrid   → BM25 + vector + RRF     │
                     │  │    ├── graph    → entity graph traversal  │
                     │  │    └── agentic  → LLM-driven search loop  │
                     │  │                                          │
                     │  │  Vertex AI Gemini 1.5 Flash (generation)  │
                     │  │  Redis Memorystore (semantic cache)       │
                     │  └──────────────────────────────────────────│
                     │                                             │
                     │  BigQuery (query logs + eval metrics)        │
                     │  Cloud Monitoring + Alerting                │
                     └─────────────────────────────────────────────┘
```

## GCP services used

| Service | Purpose | Cost (approx) |
|---------|---------|---------------|
| GCS | Document storage | ~$0.02/GB/mo |
| Document AI | PDF/DOCX parsing + OCR | $1.50/1k pages |
| Pub/Sub | Async ingestion events | ~$0.04/1M msg |
| Vertex AI Embeddings | text-embedding-004 | $0.00002/1k chars |
| Vertex AI Vector Search | ANN search index | ~$0.30/hr (deployed) |
| Vertex AI Gemini Flash | LLM generation | $0.075/1M tokens |
| GKE | Kubernetes API serving | ~$0.10/hr/node |
| Redis Memorystore | Semantic response cache | ~$0.05/GB/hr |
| BigQuery | Analytics + eval logging | ~$5/TB query |
| Cloud Build | CI/CD | 120 min/day free |
| Artifact Registry | Docker images | $0.10/GB/mo |

**Estimated total while working: ~$3–8/day**
**Destroy with `terraform destroy` when done.**

## Prerequisites

- GCP account with billing enabled
- `gcloud` CLI authenticated: `gcloud auth application-default login`
- `terraform` installed (v1.5+)
- `kubectl`, `helm`, `docker` installed
- Python 3.11

---

## PHASE 1 — GCP Infrastructure (Terraform)

### STEP 1.1 — Set up authentication

```powershell
$env:Path += ";C:\google-cloud-sdk\bin"
$env:USE_GKE_GCLOUD_AUTH_PLUGIN = "True"

gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID

# Verify
gcloud config get-value project
```

### STEP 1.2 — Configure Terraform variables

```powershell
Set-Location infra
Copy-Item terraform.tfvars.example terraform.tfvars
notepad terraform.tfvars
```

Fill in:
```hcl
project_id       = "your-actual-project-id"
region           = "us-central1"
zone             = "us-central1-a"
environment      = "dev"
gke_node_count   = 2
gke_machine_type = "n2-standard-4"
redis_memory_gb  = 1
```

### STEP 1.3 — Initialize and apply

```powershell
terraform init
terraform plan    # review: ~18 resources to create
terraform apply -auto-approve
```

What gets created:
- `google_storage_bucket` — 2 buckets (docs + processed)
- `google_pubsub_topic` + `subscription` — async ingestion pipeline
- `google_bigquery_dataset` + 2 tables — analytics
- `google_container_cluster` — GKE cluster (rag-cluster)
- `google_container_node_pool` — 2× n2-standard-4 nodes
- `google_redis_instance` — Redis Memorystore (semantic cache)
- `google_vertex_ai_index` — Vector Search index (**takes 30–90 min**)
- `google_artifact_registry_repository` — Docker image registry
- `google_service_account` × 2 + IAM bindings

> **IMPORTANT:** The Vertex AI Vector Search index takes 30–90 minutes to build.
> This is expected — it's a managed distributed ANN index.
> While it builds, proceed to Phase 2 (local dev setup).

Save the outputs — you'll need them:
```powershell
terraform output
# kubectl_command      = "gcloud container clusters get-credentials rag-cluster ..."
# gcs_docs_bucket      = "your-project-rag-docs"
# redis_host           = "10.x.x.x"
# vector_search_index_id   = "projects/.../indexes/..."
# vector_search_endpoint_id = "projects/.../indexEndpoints/..."
```

### STEP 1.4 — Configure kubectl

```powershell
# Run the kubectl_command from terraform output
gcloud container clusters get-credentials rag-cluster `
  --zone us-central1-a --project YOUR_PROJECT_ID

kubectl get nodes
# NAME                             STATUS   ROLES    AGE   VERSION
# gke-rag-cluster-rag-node-pool-xxx   Ready   <none>   5m    v1.32.0
```

---

## PHASE 2 — Local Development Setup

Run locally with ChromaDB + Redis (no cloud cost) before going to GCP.

### STEP 2.1 — Configure environment

```powershell
Set-Location ..   # back to rag-project root
Copy-Item .env.example .env
notepad .env
```

Fill in your GCP project and leave the rest as defaults for local dev:
```
GCP_PROJECT_ID=your-project-id
USE_VERTEX_VECTOR_SEARCH=false    ← ChromaDB locally
USE_DOCUMENT_AI=false             ← pypdf locally
USE_SEMANTIC_CACHE=true
```

### STEP 2.2 — Start local stack

```powershell
docker-compose -f docker/docker-compose.yml up -d

# Verify all services are up
docker-compose -f docker/docker-compose.yml ps
# NAME                STATUS
# rag-api-1           running (healthy)
# rag-chromadb-1      running (healthy)
# rag-redis-1         running (healthy)
```

### STEP 2.3 — Test health

```powershell
Invoke-RestMethod http://localhost:8080/health
# @{status=ok}

Invoke-RestMethod http://localhost:8080/ready
# @{status=ready; strategies=System.Object[]}
```

---

## PHASE 3 — Document Ingestion Pipeline

### STEP 3.1 — Upload a test document to GCS

```powershell
# Create a sample policy document for testing
$policyText = @"
Remote Work Policy
Employees may work remotely up to 3 days per week with manager approval.
Submit requests through the HR portal at least 2 business days in advance.

Data Retention Policy
Customer records are retained for 7 years per regulatory requirements.
Internal documents are retained for 3 years unless otherwise specified.

Incident Response
P1 incidents must be escalated within 15 minutes to on-call engineer.
Management notification required within 30 minutes for all P1 incidents.
"@

$policyText | Out-File -Encoding utf8 sample_policy.txt

# Upload to GCS
gsutil cp sample_policy.txt gs://$(terraform -chdir=infra output -raw gcs_docs_bucket)/
```

### STEP 3.2 — Trigger ingestion via API

```powershell
$bucket = (terraform -chdir=infra output -raw gcs_docs_bucket)

# Synchronous ingest (waits for completion)
Invoke-RestMethod -Method POST http://localhost:8080/ingest/gcs `
  -ContentType "application/json" `
  -Body (ConvertTo-Json @{
    gcs_uri   = "gs://$bucket/sample_policy.txt"
    namespace = "company-docs"
    metadata  = @{ source = "hr"; version = "2024" }
  })

# Expected:
# @{document_id=uuid; chunks_created=6; status=success; message=Ingested 1 pages into 6 chunks}
```

### STEP 3.3 — Trigger async ingestion via Pub/Sub

For large batches, use the async endpoint — it publishes to Pub/Sub and returns immediately:

```powershell
Invoke-RestMethod -Method POST http://localhost:8080/ingest/trigger-async `
  -ContentType "application/json" `
  -Body (ConvertTo-Json @{
    gcs_uri   = "gs://$bucket/sample_policy.txt"
    namespace = "company-docs"
  })
# @{status=queued; message_id=12345; gcs_uri=gs://...}
```

The ingestion worker (`pipelines/ingestion_worker.py`) picks up the message and processes it:

```powershell
# Run the worker locally
python pipelines/ingestion_worker.py
# INFO - Listening on projects/.../subscriptions/rag-ingestion-sub
# INFO - Processing: gs://...sample_policy.txt → namespace=company-docs
# INFO - Ingested 6 chunks from sample_policy.txt
```

### STEP 3.4 — Upload multiple documents

```powershell
# Upload a batch with the upload endpoint (no GCS URI needed — it handles upload)
$pdfBytes = [System.IO.File]::ReadAllBytes("your_document.pdf")
# OR: use multipart form upload via Invoke-RestMethod
```

**Understanding the chunking strategies:**

Open `src/ingestion/chunkers.py`. Three strategies exist:

| Chunker | Strategy | Best for |
|---------|----------|---------|
| `fixed` | Split every N words with overlap | Uniform documents, fast |
| `recursive` | Split at `\n\n` → `\n` → `. ` → ` ` | Mixed-format documents |
| `semantic` | Split at cosine distance breakpoints | Dense technical documents |

Change the chunker in the ingest route by modifying:
```python
chunker = ChunkerFactory.get("recursive")  # try "fixed" or "semantic"
```

---

## PHASE 4 — Multi-RAG Strategies

This is the core of the project. Understand each strategy before comparing them.

### STEP 4.1 — Naive RAG (baseline)

Query flow: `embed query → top-k cosine search → generate`

```powershell
Invoke-RestMethod -Method POST http://localhost:8080/rag/query `
  -ContentType "application/json" `
  -Body (ConvertTo-Json @{
    query     = "What is the remote work policy?"
    strategy  = "naive"
    namespace = "company-docs"
    top_k     = 5
  })
```

Expected:
```json
{
  "answer": "Employees may work remotely up to 3 days per week with manager approval...",
  "strategy": "naive",
  "sources": [{"text": "...", "score": 0.89}],
  "latency_ms": 450,
  "tokens_used": 312,
  "cached": false
}
```

**When naive fails:** Ask "What did the CEO say about our remote work policy in Q3?" —
naive retrieves "remote work policy" chunks but misses the Q3 context.

### STEP 4.2 — Advanced RAG

Query flow: `generate hypothetical answer (HyDE) → expand queries → dense search → cross-encoder rerank → compress context → generate`

```powershell
Invoke-RestMethod -Method POST http://localhost:8080/rag/query `
  -ContentType "application/json" `
  -Body (ConvertTo-Json @{
    query    = "What are the consequences of a P1 incident not being escalated?"
    strategy = "advanced"
    namespace = "company-docs"
  })
```

**What HyDE does:**
1. Gemini generates: *"When a P1 incident is not escalated, the on-call team may miss SLA deadlines..."*
2. That hypothetical answer is embedded — not the original query
3. The hypothetical answer's embedding is much closer to the actual document embeddings
4. Result: higher recall for complex questions

**What reranking does:**
- Initial retrieval: top-20 chunks by vector similarity (fast, approximate)
- Reranking: cross-encoder scores all 20 pairs (query, chunk) with a full attention model
- Result: top-5 are reordered by actual relevance (not approximate similarity)

### STEP 4.3 — Hybrid RAG

Query flow: `BM25 sparse search + vector dense search → RRF fusion → generate`

```powershell
Invoke-RestMethod -Method POST http://localhost:8080/rag/query `
  -ContentType "application/json" `
  -Body (ConvertTo-Json @{
    query    = "7 years retention compliance"
    strategy = "hybrid"
    namespace = "company-docs"
  })
```

**Why hybrid beats naive on keyword queries:**
- "7 years" is an exact keyword — BM25 will find it perfectly
- Vector search might not rank it first (semantic similarity to "seven" vs "7")
- RRF formula: `score = Σ 1/(60 + rank)` — combines both rankings without score normalization

**RRF example:**
```
Query: "7 years retention"
BM25 result: chunk_A (rank 1), chunk_B (rank 3)
Vector result: chunk_C (rank 1), chunk_A (rank 2)

RRF scores:
  chunk_A: 1/(60+1) + 1/(60+2) = 0.0311 ← wins (appears in both)
  chunk_C: 1/(60+1)             = 0.0164
  chunk_B: 1/(60+3)             = 0.0159
```

### STEP 4.4 — Graph RAG

Query flow: `extract entities → build knowledge graph → BFS traversal → retrieve connected chunks → generate`

```powershell
Invoke-RestMethod -Method POST http://localhost:8080/rag/query `
  -ContentType "application/json" `
  -Body (ConvertTo-Json @{
    query    = "How do HR policies relate to data retention requirements?"
    strategy = "graph"
    namespace = "company-docs"
  })
```

**How the graph is built (see `src/retrieval/graph.py`):**
1. For each document chunk, extract named entities (people, orgs, policies, dates)
2. Connect entities that co-occur in the same chunk: `HR Policy ←→ Data Retention`
3. At query time: find nodes matching query entities, do BFS to find connected information

**When graph beats vector:**
- Multi-hop questions: "What process connects HR policies and compliance requirements?"
- Vector embeds the whole chunk — graph tracks individual entity relationships
- Production graph RAG uses spaCy NER + Neo4j; this project uses regex + NetworkX

### STEP 4.5 — Agentic RAG

Query flow: `LLM decides tools → search → reflect → search again → synthesise`

```powershell
Invoke-RestMethod -Method POST http://localhost:8080/rag/query `
  -ContentType "application/json" `
  -Body (ConvertTo-Json @{
    query    = "Summarize all policies related to employee obligations and compliance deadlines"
    strategy = "agentic"
    namespace = "company-docs"
  })
```

**How the agent loop works (see `src/retrieval/agentic.py`):**
```
Iteration 1:
  Agent decides: {"action": "search_documents", "args": {"query": "employee obligations"}}
  Gets chunks about obligations
  
Iteration 2:
  Agent sees partial context, decides: {"action": "search_documents", "args": {"query": "compliance deadlines"}}
  Gets more chunks
  
Iteration 3:
  Agent has enough context: {"action": "final", "answer": "..."}
```

**When agentic beats fixed pipelines:**
- Ambiguous multi-part questions that need multiple search passes
- When the first search reveals missing context the agent can search for
- Trade-off: 3–10× higher latency and token cost vs. naive

### STEP 4.6 — Compare all strategies side by side

```powershell
Invoke-RestMethod -Method POST http://localhost:8080/rag/compare `
  -ContentType "application/json" `
  -Body (ConvertTo-Json @{
    query      = "What is the escalation procedure for critical incidents?"
    strategies = @("naive", "advanced", "hybrid")
    namespace  = "company-docs"
  })
```

Expected response shows all three answers + latency side by side:
```json
{
  "query": "What is the escalation procedure...",
  "results": [
    {"strategy": "naive",    "latency_ms": 420,  "tokens_used": 289, "answer": "..."},
    {"strategy": "advanced", "latency_ms": 1840, "tokens_used": 412, "answer": "..."},
    {"strategy": "hybrid",   "latency_ms": 680,  "tokens_used": 310, "answer": "..."}
  ]
}
```

Notice:
- `naive` is fastest but may miss context
- `advanced` is slowest (HyDE + rerank adds 2 Gemini calls)
- `hybrid` balances quality and speed

---

## PHASE 5 — Switch to Vertex AI Vector Search (Production)

Once the Terraform index finishes building (~60 min from Phase 1):

### STEP 5.1 — Get the index IDs

```powershell
Set-Location infra
$indexId    = terraform output -raw vector_search_index_id
$endpointId = terraform output -raw vector_search_endpoint_id
$redisHost  = terraform output -raw redis_host
```

### STEP 5.2 — Re-ingest with Vertex AI Vector Search

Update `.env`:
```
USE_VERTEX_VECTOR_SEARCH=true
VECTOR_SEARCH_INDEX_ID=<from terraform output>
VECTOR_SEARCH_ENDPOINT_ID=<from terraform output>
REDIS_HOST=<redis_host from terraform>
```

Restart and re-ingest:
```powershell
docker-compose -f docker/docker-compose.yml restart rag-api
```

Re-run the ingestion from Phase 3. Now chunks go into Vertex AI Vector Search
instead of ChromaDB — same API, different backend.

**Why Vertex AI Vector Search at scale:**
- Handles billions of vectors (ChromaDB handles millions)
- STREAM_UPDATE mode: index updates in seconds, not batch rebuilds
- 99.9% SLA, multi-region replicas
- Dedicated compute (you control replicas, not shared)

---

## PHASE 6 — RAGAS Evaluation

Run the evaluation pipeline to compare strategies objectively.

### STEP 6.1 — Run evaluation for each strategy

```powershell
# Evaluate hybrid strategy
Invoke-RestMethod -Method POST http://localhost:8080/evaluate/run `
  -ContentType "application/json" `
  -Body (ConvertTo-Json @{ strategy = "hybrid"; namespace = "company-docs" })
```

Expected:
```json
{
  "strategy": "hybrid",
  "metrics": {
    "faithfulness": 0.92,
    "answer_relevancy": 0.88,
    "context_precision": 0.85,
    "context_recall": 0.79,
    "answer_correctness": 0.83
  },
  "num_questions": 5,
  "run_id": "eval-hybrid-abc12345"
}
```

### STEP 6.2 — Run all strategies and compare

```powershell
foreach ($strategy in @("naive", "advanced", "hybrid", "graph", "agentic")) {
  Write-Host "Evaluating $strategy..."
  Invoke-RestMethod -Method POST http://localhost:8080/evaluate/run `
    -ContentType "application/json" `
    -Body (ConvertTo-Json @{ strategy = $strategy; namespace = "company-docs" })
}
```

### STEP 6.3 — View eval history in BigQuery

```powershell
bq query --use_legacy_sql=false "
  SELECT strategy,
         AVG(faithfulness)       AS avg_faithfulness,
         AVG(answer_relevancy)   AS avg_relevancy,
         AVG(context_precision)  AS avg_precision,
         AVG(context_recall)     AS avg_recall,
         COUNT(*)                AS runs
  FROM \`${env:GCP_PROJECT_ID}.rag_analytics.evaluations\`
  GROUP BY strategy
  ORDER BY avg_faithfulness DESC
"
```

**Understanding RAGAS metrics:**

| Metric | Measures | Formula |
|--------|---------|---------|
| `faithfulness` | Does the answer come from the context? | % of claims in answer supported by context |
| `answer_relevancy` | Does the answer address the question? | Cosine sim of answer → question |
| `context_precision` | Are retrieved chunks relevant? | % of relevant chunks in top-k |
| `context_recall` | Were relevant chunks retrieved? | % of ground truth facts covered |
| `answer_correctness` | Is the answer factually correct? | F1 against ground truth |

Add more questions to `src/evaluation/test_dataset.json` for a meaningful eval.

---

## PHASE 7 — Deploy to GKE

### STEP 7.1 — Build and push image to Artifact Registry

```powershell
Set-Location ..  # rag-project root

$registry = (terraform -chdir=infra output -raw artifact_registry)
$image    = "$registry/rag-api"

# Build
docker build -f docker/Dockerfile -t "${image}:latest" .

# Push
gcloud auth configure-docker us-central1-docker.pkg.dev
docker push "${image}:latest"
```

### STEP 7.2 — Create Kubernetes secret with config

```powershell
kubectl create secret generic rag-config `
  --from-literal=gcp_project_id=$env:GCP_PROJECT_ID `
  --from-literal=redis_host=(terraform -chdir=infra output -raw redis_host) `
  --from-literal=vector_search_index_id=(terraform -chdir=infra output -raw vector_search_index_id) `
  --from-literal=vector_search_endpoint_id=(terraform -chdir=infra output -raw vector_search_endpoint_id)
```

### STEP 7.3 — Deploy

```powershell
# Update image reference
(Get-Content k8s/deployment.yaml) `
  -replace "REGISTRY/rag-api:latest", "${image}:latest" `
  -replace "PROJECT_ID", $env:GCP_PROJECT_ID `
  | Set-Content k8s/deployment.yaml

kubectl apply -f k8s/
kubectl rollout status deployment/rag-api --timeout=5m

kubectl get pods
# NAME                       READY   STATUS    RESTARTS
# rag-api-xxx-yyy            1/1     Running   0
# rag-api-zzz-www            1/1     Running   0
```

### STEP 7.4 — Get the external IP and test

```powershell
kubectl get service rag-api
# NAME      TYPE           CLUSTER-IP    EXTERNAL-IP   PORT(S)
# rag-api   LoadBalancer   10.x.x.x      34.x.x.x      80:31xxx/TCP

$ip = (kubectl get service rag-api -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

Invoke-RestMethod -Method POST "http://${ip}/rag/query" `
  -ContentType "application/json" `
  -Body (ConvertTo-Json @{
    query     = "What is the remote work policy?"
    strategy  = "hybrid"
    namespace = "company-docs"
  })
```

### STEP 7.5 — Verify HPA is working

```powershell
kubectl get hpa
# NAME      REFERENCE             TARGETS         MINPODS   MAXPODS   REPLICAS
# rag-api   Deployment/rag-api    22%/60%         2         20        2

# Send load to trigger scale-up
1..200 | ForEach-Object {
  Invoke-RestMethod -Method POST "http://${ip}/rag/query" `
    -ContentType "application/json" `
    -Body (ConvertTo-Json @{ query = "test"; strategy = "naive"; namespace = "company-docs" }) |
    Out-Null
}

# Watch HPA scale up
kubectl get hpa -w
# REPLICAS column increases from 2 → 4 → 6 as CPU goes above 60%
```

---

## PHASE 8 — CI/CD with Cloud Build + GitHub Actions

### STEP 8.1 — Set up Workload Identity Federation

```powershell
# Create WIF pool and provider (replaces service account keys)
gcloud iam workload-identity-pools create "github-pool" `
  --project=$env:GCP_PROJECT_ID `
  --location="global" `
  --display-name="GitHub Actions Pool"

gcloud iam workload-identity-pools providers create-oidc "github-provider" `
  --project=$env:GCP_PROJECT_ID `
  --location="global" `
  --workload-identity-pool="github-pool" `
  --display-name="GitHub Provider" `
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" `
  --issuer-uri="https://token.actions.githubusercontent.com"
```

### STEP 8.2 — Add secrets to GitHub

Go to: **GitHub repo → Settings → Secrets → Actions**

| Secret | Value |
|--------|-------|
| `GCP_PROJECT_ID` | your GCP project ID |
| `WIF_PROVIDER` | `projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/providers/github-provider` |
| `WIF_SERVICE_ACCOUNT` | `rag-api-sa@YOUR_PROJECT.iam.gserviceaccount.com` |

### STEP 8.3 — Trigger the pipeline

```powershell
git checkout -b feature/test-pipeline
# Make a small change to src/api/main.py
git add . && git commit -m "test: trigger CI"
git push -u origin feature/test-pipeline
# Open PR → CI runs (pytest + docker build)
# Merge → CD runs (build + push + deploy to GKE)
```

---

## PHASE 9 — Observability

### STEP 9.1 — View Prometheus metrics

```powershell
kubectl port-forward svc/rag-api 8080:80

# Strategy-level request counts
Invoke-RestMethod http://localhost:8080/metrics | Select-String "rag_requests_total"
# rag_requests_total{method="POST",endpoint="/rag/query",strategy="hybrid",status="200"} 42

# Latency histogram
Invoke-RestMethod http://localhost:8080/metrics | Select-String "rag_request_latency"
```

### STEP 9.2 — View BigQuery query logs

```powershell
bq query --use_legacy_sql=false "
  SELECT strategy,
         COUNT(*)          AS queries,
         AVG(latency_ms)   AS avg_latency_ms,
         SUM(tokens_used)  AS total_tokens,
         COUNTIF(cached)   AS cache_hits
  FROM \`${env:GCP_PROJECT_ID}.rag_analytics.queries\`
  WHERE DATE(timestamp) = CURRENT_DATE()
  GROUP BY strategy
  ORDER BY queries DESC
"
```

### STEP 9.3 — Set up alerting

```powershell
# Alert: P99 latency > 5 seconds
gcloud alpha monitoring policies create --policy-from-file=- << 'EOF'
{
  "displayName": "RAG High Latency",
  "conditions": [{
    "displayName": "P99 latency > 5s",
    "conditionThreshold": {
      "filter": "metric.type=\"custom.googleapis.com/rag_request_latency_seconds\"",
      "comparison": "COMPARISON_GT",
      "thresholdValue": 5,
      "duration": "60s"
    }
  }]
}
EOF
```

---

## PHASE 10 — Semantic Cache Deep Dive

### STEP 10.1 — Test cache hit

```powershell
# First call — cache miss, full pipeline runs
$t1 = Measure-Command {
  Invoke-RestMethod -Method POST http://localhost:8080/rag/query `
    -ContentType "application/json" `
    -Body (ConvertTo-Json @{ query = "What is the remote work policy?"; strategy = "hybrid"; namespace = "company-docs" })
}
Write-Host "First call: $($t1.TotalMilliseconds)ms"

# Second call — cache hit (Redis lookup, no Gemini call)
$t2 = Measure-Command {
  $r = Invoke-RestMethod -Method POST http://localhost:8080/rag/query `
    -ContentType "application/json" `
    -Body (ConvertTo-Json @{ query = "What is the remote work policy?"; strategy = "hybrid"; namespace = "company-docs" })
  Write-Host "cached=$($r.cached)"
}
Write-Host "Second call: $($t2.TotalMilliseconds)ms"
# First:  ~800ms  (full pipeline)
# Second: ~20ms   (Redis lookup)
```

Cache keys are SHA-256 of `namespace:strategy:normalized_query`.
Exact match only — for semantic (fuzzy) cache, embed the query and use vector similarity.

---

## Common errors and fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `google.api_core.exceptions.NotFound: index not found` | Vector Search index still building | Wait 30–90 min or use ChromaDB (`USE_VERTEX_VECTOR_SEARCH=false`) |
| `PermissionDenied: aiplatform.googleapis.com` | API not enabled or wrong SA | Run `terraform apply` to enable APIs + create IAM bindings |
| `Connection refused` on ChromaDB | Docker not running | `docker-compose -f docker/docker-compose.yml up -d` |
| `RAGAS evaluation stuck` | Gemini rate limit | RAGAS makes many Gemini calls — add `time.sleep(1)` between eval questions |
| `HPA TARGETS: <unknown>/60%` | Metrics server not installed | `kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml` |
| `ImagePullBackOff` on GKE | Wrong image path | Verify Artifact Registry URI: `us-central1-docker.pkg.dev/PROJECT/rag-repo/rag-api` |
| Pub/Sub message not processed | Worker not running | `python pipelines/ingestion_worker.py` |
| `BM25 returns empty` | No documents in vector store | Ingest documents first (Phase 3) |

---

## PHASE 12 — LLMOps: MLflow + Feedback Collection

### STEP 12.1 — Start MLflow locally

```powershell
docker-compose -f docker/docker-compose.yml up -d

# MLflow UI available at:
Start-Process http://localhost:5000
```

You will see experiments auto-created on first query:
- `rag-queries` — one run per query (strategy, latency, tokens, model tier)
- `rag-eval` — RAGAS evaluation runs
- `rag-finetune` — fine-tuning jobs

### STEP 12.2 — Make queries and watch MLflow populate

```powershell
# Make 10 queries with different strategies
$queries = @("What is the remote work policy?", "Explain the incident escalation process", "Compare leave policies")
foreach ($q in $queries) {
  foreach ($strategy in @("naive", "hybrid", "advanced")) {
    Invoke-RestMethod -Method POST http://localhost:8080/rag/query `
      -ContentType "application/json" `
      -Body (ConvertTo-Json @{ query = $q; strategy = $strategy; namespace = "company-docs" }) |
      Out-Null
  }
}
```

Go to http://localhost:5000 → Experiments → rag-queries
You can now see:
- Which strategy is slowest (latency_ms)
- Which uses most tokens (tokens_used)
- Which model tier was auto-selected (model_tier tag)

### STEP 12.3 — Understand the Model Router

The router automatically selected Flash vs Pro for each query. Check what it decided:

```powershell
# Simple factual → Flash
Invoke-RestMethod -Method POST http://localhost:8080/rag/query `
  -ContentType "application/json" `
  -Body (ConvertTo-Json @{ query = "What is the leave policy?"; strategy = "hybrid"; namespace = "company-docs" })
# model_tier in MLflow: "flash"

# Analytical → Pro
Invoke-RestMethod -Method POST http://localhost:8080/rag/query `
  -ContentType "application/json" `
  -Body (ConvertTo-Json @{ query = "Analyze and compare the remote work policy with the leave policy and explain the implications for employees"; strategy = "hybrid"; namespace = "company-docs" })
# model_tier in MLflow: "pro"
```

Open `src/model_router/router.py` to see the routing rules.
Tune `ANALYTICAL_PATTERNS` and `_is_complex()` to match your domain.

### STEP 12.4 — Collect user feedback

```powershell
# Submit thumbs-up (rating=5)
Invoke-RestMethod -Method POST http://localhost:8080/feedback/submit `
  -ContentType "application/json" `
  -Body (ConvertTo-Json @{
    query    = "What is the remote work policy?"
    answer   = "Employees may work remotely up to 3 days per week..."
    strategy = "hybrid"
    rating   = 5
    comment  = "Accurate and concise"
  })

# Submit thumbs-down (rating=1) — this feeds the fine-tuning pipeline
Invoke-RestMethod -Method POST http://localhost:8080/feedback/submit `
  -ContentType "application/json" `
  -Body (ConvertTo-Json @{
    query    = "What are the compliance deadlines?"
    answer   = "I don't have enough information..."
    strategy = "naive"
    rating   = 1
    comment  = "Should know this — it's in the policy docs"
  })

# Check feedback stats
Invoke-RestMethod "http://localhost:8080/feedback/stats?days=7"
```

---

## PHASE 13 — LLMOps: Prompt Registry + A/B Testing

### STEP 13.1 — Register a new system prompt version

```powershell
# Register prompt v2 — more concise instructions
Invoke-RestMethod -Method POST http://localhost:8080/llmops/register-prompt `
  -ContentType "application/json" `
  -Body (ConvertTo-Json @{
    name    = "system"
    content = "You are a precise enterprise assistant. Answer in 3 sentences or less using only the provided context. If unsure, say so."
    author  = "your-name"
  })

# Expected:
# @{name=system; version=2; status=registered; message=...}
```

Go to http://localhost:5000 → Experiments → (you'll see a run for the prompt registration)
The prompt content is stored as an MLflow artifact — you can roll back to v1 anytime.

### STEP 13.2 — Evaluate the new prompt before promoting

```powershell
# Run RAGAS eval to measure if v2 is better
Invoke-RestMethod -Method POST "http://localhost:8080/llmops/trigger-eval?strategy=hybrid&namespace=company-docs"
```

Compare eval results in MLflow → rag-eval experiment.
If v2 scores higher on `answer_relevancy`, promote it:

```powershell
# View all prompt versions
Invoke-RestMethod "http://localhost:8080/llmops/prompt-versions?name=system"
```

---

## PHASE 14 — LLMOps: Deploy Argo Workflows

### STEP 14.1 — Install Argo Workflows on GKE

```powershell
# Get GKE credentials first
gcloud container clusters get-credentials rag-cluster --zone us-central1-a --project $env:GCP_PROJECT_ID

# Install Argo Workflows
kubectl create namespace argo
kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/latest/download/quick-start-minimal.yaml

kubectl wait --for=condition=Available deployment/workflow-controller -n argo --timeout=120s
```

### STEP 14.2 — Deploy MLflow to GKE

```powershell
# Create secret with all config
kubectl create secret generic rag-config `
  --from-literal=gcp_project_id=$env:GCP_PROJECT_ID `
  --from-literal=redis_host=(terraform -chdir=infra output -raw redis_host) `
  --from-literal=gcs_processed_bucket=(terraform -chdir=infra output -raw gcs_docs_bucket)-processed `
  --from-literal=mlflow_tracking_uri="http://mlflow.default.svc.cluster.local:5000" `
  --from-literal=vector_search_index_id=(terraform -chdir=infra output -raw vector_search_index_id) `
  --from-literal=vector_search_endpoint_id=(terraform -chdir=infra output -raw vector_search_endpoint_id)

# Deploy MLflow
kubectl apply -f k8s/mlflow.yaml
kubectl rollout status deployment/mlflow --timeout=3m

# Access MLflow UI
kubectl port-forward svc/mlflow 5000:5000
Start-Process http://localhost:5000
```

### STEP 14.3 — Deploy the nightly eval CronWorkflow

```powershell
# Update the image reference first
(Get-Content argo/eval-cron.yaml) `
  -replace "YOUR_REGISTRY/rag-api:latest", "${image}:latest" |
  Set-Content argo/eval-cron.yaml

# Submit the CronWorkflow
kubectl apply -f argo/eval-cron.yaml -n argo

kubectl get cronworkflow -n argo
# NAME               SCHEDULE    TIMEZONE   LASTSUCCEEDED   AGE
# rag-nightly-eval   0 2 * * *   UTC                        5s

# Trigger immediately to test (don't wait for 2am)
argo submit --from cronwf/rag-nightly-eval -n argo --watch
```

### STEP 14.4 — Deploy drift detection + feedback curator

```powershell
(Get-Content argo/drift-detection.yaml) `
  -replace "YOUR_REGISTRY/rag-api:latest", "${image}:latest" |
  Set-Content argo/drift-detection.yaml

(Get-Content argo/feedback-curator.yaml) `
  -replace "YOUR_REGISTRY/rag-api:latest", "${image}:latest" |
  Set-Content argo/feedback-curator.yaml

kubectl apply -f argo/drift-detection.yaml -n argo
kubectl apply -f argo/feedback-curator.yaml -n argo

kubectl get cronworkflow -n argo
# NAME                    SCHEDULE      TIMEZONE
# rag-nightly-eval        0 2 * * *     UTC
# rag-drift-detection     0 4 * * 1     UTC   (Mondays 4am)
# rag-feedback-curator    0 3 * * 0     UTC   (Sundays 3am)
```

---

## PHASE 15 — LLMOps: Drift Detection in Practice

### STEP 15.1 — Trigger a drift check manually

```powershell
# Check drift between last 30 days (reference) vs last 7 days (current)
Invoke-RestMethod -Method POST "http://localhost:8080/llmops/trigger-drift-check?reference_days=30&current_days=7"
```

Expected (no drift yet — not enough varied data):
```json
{
  "drift_detected": false,
  "share_of_drifted_columns": 0.0,
  "reference_size": 100,
  "current_size": 10,
  "reason": "insufficient_data"
}
```

### STEP 15.2 — Simulate drift by changing query patterns

```powershell
# Send queries about a completely new topic (simulate new product launch)
1..50 | ForEach-Object {
  Invoke-RestMethod -Method POST http://localhost:8080/rag/query `
    -ContentType "application/json" `
    -Body (ConvertTo-Json @{
      query    = "What is the AI governance policy for large language models?"
      strategy = "hybrid"
      namespace = "company-docs"
    }) | Out-Null
}

# Re-run drift check
Invoke-RestMethod -Method POST "http://localhost:8080/llmops/trigger-drift-check?reference_days=30&current_days=1"
```

Expected after 50 new-topic queries:
```json
{
  "drift_detected": true,
  "share_of_drifted_columns": 0.33,
  "drifted_columns": ["query_length"],
  "report_path": "/tmp/drift_report.html"
}
```

**What to do when drift is detected:**
1. Review the query patterns in BigQuery — what new topics are users asking about?
2. Find/create documents covering those topics
3. Ingest them: `POST /ingest/gcs` with the new documents
4. Re-run eval to confirm retrieval quality improved

---

## PHASE 16 — LLMOps: Fine-Tuning Pipeline (requires GPU)

### STEP 16.1 — Add GPU node pool via Terraform

```powershell
Set-Location infra
terraform apply -target=google_container_node_pool.gpu_nodes -auto-approve
# Creates n1-standard-4 + T4 GPU node pool (starts at 0 nodes — KEDA scales it up)
```

### STEP 16.2 — Install KEDA

```powershell
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
helm install keda kedacore/keda --namespace keda --create-namespace

kubectl apply -f k8s/keda.yaml
```

### STEP 16.3 — Manually trigger a fine-tune run

First, collect enough feedback (at least 50 thumbs-down):
```powershell
# Check feedback count
Invoke-RestMethod "http://localhost:8080/feedback/stats?days=30"
```

Then trigger the fine-tuning pipeline:
```powershell
argo submit argo/fine-tune-pipeline.yaml -n argo `
  -p dataset-version=$(Get-Date -Format "yyyyMMdd") `
  -p app-image="${image}:latest" `
  --watch
```

Watch KEDA scale up the GPU node automatically:
```powershell
# In another terminal
kubectl get nodes -w
# The gpu-node-pool node appears as KEDA detects the running workflow
```

### STEP 16.4 — Promote the fine-tuned adapter

After fine-tuning completes, the adapter is registered as `@challenger` in MLflow.
Run eval, compare, then promote:

```powershell
# Compare challenger vs champion
Invoke-RestMethod "http://localhost:8080/llmops/model-versions?model_name=rag-llm-adapter"

# If challenger metrics are better, promote
Invoke-RestMethod -Method POST http://localhost:8080/llmops/promote-model `
  -ContentType "application/json" `
  -Body (ConvertTo-Json @{
    model_name = "rag-llm-adapter"
    from_alias = "challenger"
    to_alias   = "champion"
  })
```

Enable the fine-tuned model in the API:
```powershell
# Update .env
# FINE_TUNED_AVAILABLE=true
# VLLM_ADAPTER_ENDPOINT=http://vllm-service:8000

# Restart the API
docker-compose -f docker/docker-compose.yml restart rag-api
```

---

## PHASE 11 — Destroy (stop billing)

```powershell
# Delete GKE workloads first
kubectl delete -f k8s/

# Destroy all GCP resources
Set-Location infra
terraform destroy -auto-approve
# Takes ~15 minutes
# GCS buckets, BQ, Pub/Sub, GKE, Redis, Vector Search index all deleted
```

Verify in GCP Console:
- Kubernetes Engine → Clusters (should be empty)
- Vertex AI → Vector Search (index deleted)
- Memorystore → Redis instances (deleted)

---

## What you learned in this project

### RAG strategy decision framework

| Query type | Best strategy | Why |
|-----------|--------------|-----|
| Simple factual | naive | Fast, low cost |
| Keyword + semantic | hybrid | RRF fusion beats either alone |
| Complex multi-hop | advanced | HyDE + rerank recovers missed context |
| Entity relationships | graph | Traverses connections, not just similarity |
| Ambiguous / exploratory | agentic | LLM refines the search itself |

### GCP architecture patterns

- **GCS → Pub/Sub → Worker** — decoupled async ingestion (no blocking)
- **Vertex AI Vector Search** — enterprise ANN at billions of vectors, ms latency
- **Workload Identity** — no service account keys in CI/CD
- **BigQuery partitioned tables** — time-based partitioning keeps analytics queries cheap
- **HPA with custom metrics** — scale pods based on CPU/memory, not just replica count

### Enterprise readiness checklist

**RAG layer**
- [x] 5 retrieval strategies (naive / advanced / hybrid / graph / agentic)
- [x] Multi-tenant namespaces (per-namespace collections)
- [x] Guardrails (prompt injection detection, PII redaction)
- [x] Semantic caching (Redis, 95%+ cache hit on repeated queries)
- [x] HPA autoscaling (2→20 pods based on load)
- [x] Dead letter queue (failed ingestion messages don't vanish)

**LLMOps layer**
- [x] Model Router (Flash/Pro/fine-tuned selected per query complexity)
- [x] Prompt Registry (versioned prompts tracked in MLflow, rollback in <1 min)
- [x] MLflow experiment tracking (every query, eval run, fine-tune job logged)
- [x] User feedback collection (👍/👎 → BigQuery → training data pipeline)
- [x] Nightly RAGAS eval (Argo CronWorkflow detects regressions before users do)
- [x] Weekly drift detection (Evidently catches domain shift automatically)
- [x] Weekly feedback curation (bad answers → curated training pairs → GCS)
- [x] QLoRA fine-tuning pipeline (Argo Workflow on GPU, KEDA scale-to-zero)
- [x] Model Registry (@champion / @challenger promotion workflow)
- [x] KEDA GPU scaling (GPU node pool scales 0→1→0, saves ~98% GPU cost)

**Infrastructure**
- [x] BigQuery audit log (every query + eval + feedback logged)
- [x] Workload Identity (no long-lived credentials)
- [x] CI/CD (GitHub Actions → Artifact Registry → GKE)
- [x] Vertex AI Vector Search (enterprise ANN at billions of vectors)
