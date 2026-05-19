# Enterprise Multi-RAG on GCP

End-to-end enterprise RAG system with 5 retrieval strategies, deployed on Google Cloud Platform.

## 5 RAG Strategies

| Strategy | How it works | Best for | Relative cost |
|----------|-------------|---------|--------------|
| **Naive** | Embed → top-k cosine | Simple factual queries | 1× |
| **Advanced** | HyDE + multi-query + rerank + compress | Complex questions with ambiguity | 4× |
| **Hybrid** | BM25 + vector → RRF fusion | Keyword + semantic queries | 1.5× |
| **Graph** | Entity extraction → knowledge graph traversal | Relationship questions | 2× |
| **Agentic** | LLM drives the search loop iteratively | Multi-hop, exploratory queries | 6× |

## GCP Architecture

```
GCS Bucket ──► Pub/Sub ──► Ingestion Worker
                                   │
                         ┌─────────┴──────────┐
                         │                    │
               Vertex AI Embeddings    Document AI
               (text-embedding-004)    (OCR/parse)
                         │
                 Vertex AI Vector Search
                 (enterprise ANN index)
                         │
              ┌──────────┴───────────┐
              │     RAG API (GKE)   │
              │  /rag/query          │
              │  /rag/compare        │
              │  /ingest/gcs         │
              │  /evaluate/run       │
              └──────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
   Gemini Flash    Redis Cache     BigQuery Logs
   (generation)   (responses)     (analytics)
```

## Quick Start

```powershell
# 1. Provision GCP infra
Set-Location infra
Copy-Item terraform.tfvars.example terraform.tfvars   # fill in project_id
terraform init && terraform apply -auto-approve

# 2. Run locally (ChromaDB + Redis via Docker Compose)
Set-Location ..
Copy-Item .env.example .env   # fill in GCP_PROJECT_ID
docker-compose -f docker/docker-compose.yml up -d

# 3. Ingest a document
Invoke-RestMethod -Method POST http://localhost:8080/ingest/gcs `
  -ContentType "application/json" `
  -Body '{"gcs_uri":"gs://YOUR_BUCKET/doc.pdf","namespace":"default"}'

# 4. Query with different strategies
Invoke-RestMethod -Method POST http://localhost:8080/rag/query `
  -ContentType "application/json" `
  -Body '{"query":"your question","strategy":"hybrid","namespace":"default"}'

# 5. Compare strategies
Invoke-RestMethod -Method POST http://localhost:8080/rag/compare `
  -ContentType "application/json" `
  -Body '{"query":"your question","strategies":["naive","hybrid","advanced"],"namespace":"default"}'
```

## Follow the full guide

See **[PROJECT.md](PROJECT.md)** for the complete step-by-step walkthrough across 11 phases:

1. GCP Infrastructure (Terraform)
2. Local Development Setup
3. Document Ingestion Pipeline
4. Multi-RAG Strategies (all 5)
5. Vertex AI Vector Search (production)
6. RAGAS Evaluation
7. Deploy to GKE
8. CI/CD (GitHub Actions + WIF)
9. Observability (Prometheus + BigQuery)
10. Semantic Cache
11. Destroy (stop billing)

## Project structure

```
rag-project/
├── PROJECT.md                  ← Full step-by-step guide
├── src/
│   ├── api/                    ← FastAPI (routes, models, middleware)
│   ├── ingestion/              ← GCS loader, chunkers, Vertex AI embedder
│   ├── retrieval/              ← 5 strategy implementations
│   ├── generation/             ← Gemini client + prompt templates
│   ├── evaluation/             ← RAGAS + BigQuery logger
│   ├── guardrails/             ← Input/output safety filters
│   └── cache/                  ← Redis semantic cache
├── infra/                      ← Terraform (all GCP resources)
├── k8s/                        ← Kubernetes manifests (Deployment, HPA)
├── pipelines/                  ← Pub/Sub ingestion worker
├── docker/                     ← Dockerfile + docker-compose (local dev)
└── .github/workflows/          ← CI/CD (GitHub Actions)
```
