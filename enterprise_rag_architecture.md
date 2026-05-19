# Enterprise RAG + LLMOps — Integrated Architecture

---

## Why this combination exists

Enterprise RAG answers questions from documents. LLMOps makes it better over time.

Without LLMOps, enterprise RAG is a static system — it works on day 1, but silently
degrades when the LLM provider updates model weights, when your document domain shifts,
when a prompt change breaks 20% of answers, or when token costs double unnoticed.

LLMOps adds five continuous feedback loops:

  1. Quality Loop    — RAGAS detects answer quality degradation → triggers action
  2. Feedback Loop   — user thumbs-down → labeled training data → fine-tune → better model
  3. Cost Loop       — token cost trending up → route expensive queries to cheaper model
  4. Experiment Loop — A/B test new prompt/strategy → canary deploy the winner
  5. Drift Loop      — query distribution shifts → Evidently alerts → update training data

The two systems share one data layer (BigQuery) and one model layer (Model Registry).
RAG feeds data into LLMOps. LLMOps feeds improved models back into RAG.

---

## Architecture Overview

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                     ENTERPRISE RAG + LLMOps                                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  ┌─────────────────────────────────────────────────────────────────────┐    ║
║  │              OFFLINE: DOCUMENT INDEXING PIPELINE                    │    ║
║  │                                                                     │    ║
║  │  GCS / SharePoint / Confluence / S3                                 │    ║
║  │       │                                                             │    ║
║  │  Document Parser (PDF / DOCX / HTML / images via OCR)              │    ║
║  │       │                                                             │    ║
║  │  Chunking Engine (fixed / recursive / semantic)                     │    ║
║  │       │                                                             │    ║
║  │  Embedding Model ←─── pulled from Model Registry (versioned)        │    ║
║  │       │                                                             │    ║
║  │  ┌────┴──────────────────────┐    ┌───────────────────────┐        │    ║
║  │  │  Vector Index             │    │  Metadata Store        │        │    ║
║  │  │  (Vertex AI Vector Search)│    │  (BigQuery: chunk_id,  │        │    ║
║  │  │                           │    │  source, date, ACL)    │        │    ║
║  │  └───────────────────────────┘    └───────────────────────┘        │    ║
║  │                                                                     │    ║
║  │  Feast Feature Store ← ensures training and serving use same        │    ║
║  │  (Redis online store)   embedding model and preprocessing           │    ║
║  └─────────────────────────────────────────────────────────────────────┘    ║
║                                                                              ║
║  ┌─────────────────────────────────────────────────────────────────────┐    ║
║  │              ONLINE: QUERY PIPELINE (per request)                   │    ║
║  │                                                                     │    ║
║  │  User / AI Copilot Interface                                        │    ║
║  │       │                                                             │    ║
║  │  API Gateway                                                        │    ║
║  │  ├── Rate limiting + Load balancing                                 │    ║
║  │  └── OpenTelemetry trace starts here ──────────────────────┐       │    ║
║  │       │                                                     │       │    ║
║  │  Authentication & Authorization                             │       │    ║
║  │  ├── SSO / OAuth2 / JWT                                     │       │    ║
║  │  └── RBAC → namespace isolation (multi-tenant)              │       │    ║
║  │       │                                                     │       │    ║
║  │  Conversation Memory                                        │       │    ║
║  │  ├── Short-term: last N turns (Redis)                       │       │    ║
║  │  └── Long-term: user profile, past decisions (Firestore)    │       │    ║
║  │       │                                                     │       │    ║
║  │  Intent Router ←── Prompt version from Prompt Registry      │       │    ║
║  │  ├── Query type: factual / analytical / action              │       │    ║
║  │  ├── Complexity: single-hop / multi-hop / ambiguous         │       │    ║
║  │  └── Route: RAG / action / direct LLM / hybrid             │       │    ║
║  │       │                                                     │       │    ║
║  │  [Semantic Cache Check] ←── Redis Memorystore               │       │    ║
║  │  ├── HIT  → skip to Response (0 tokens, <20ms)             │       │    ║
║  │  └── MISS ↓                                                │       │    ║
║  │       │                                                     │       │    ║
║  │  Query Understanding                                        │       │    ║
║  │  ├── Decomposition (complex → sub-queries)                  │       │    ║
║  │  ├── HyDE (generate hypothetical answer → embed that)       │       │    ║
║  │  ├── Query expansion + keyword extraction                   │       │    ║
║  │  └── Query logged to BigQuery ─────────────────────────────┼──┐   │    ║
║  │       │                                                     │  │   │    ║
║  │  Hybrid Retrieval                                           │  │   │    ║
║  │  ├── Dense: Vertex AI Vector Search (semantic)              │  │   │    ║
║  │  ├── Sparse: BM25 (keyword)                                 │  │   │    ║
║  │  ├── Graph: Neo4j / NetworkX (relationships)                │  │   │    ║
║  │  ├── Structured: SQL / ERP / CRM                           │  │   │    ║
║  │  └── Multi-modal: CLIP / Whisper (images / audio)          │  │   │    ║
║  │       │                                                     │  │   │    ║
║  │  Re-ranking                                                 │  │   │    ║
║  │  ├── Cross-encoder (ms-marco / Cohere Rerank)              │  │   │    ║
║  │  ├── MMR (diversity — avoid duplicate chunks)              │  │   │    ║
║  │  └── ACL filter (remove chunks user lacks access to)       │  │   │    ║
║  │       │                                                     │  │   │    ║
║  │  Context Assembly                                           │  │   │    ║
║  │  ├── Context window budget management                       │  │   │    ║
║  │  ├── System prompt ←── Prompt Registry (versioned)          │  │   │    ║
║  │  └── Few-shot examples + source metadata                   │  │   │    ║
║  │       │                                                     │  │   │    ║
║  │  Guardrails (PRE-generation)                                │  │   │    ║
║  │  ├── Prompt injection detection                             │  │   │    ║
║  │  └── PII filter on retrieved chunks                        │  │   │    ║
║  │       │                                                     │  │   │    ║
║  │  LLM Generation ←── Model Registry (versioned, canary)     │  │   │    ║
║  │  ├── Model Router (by complexity + cost budget)            │  │   │    ║
║  │  │   ├── Tier 1: Gemini Flash (simple factual, cheap)      │  │   │    ║
║  │  │   ├── Tier 2: Gemini Pro (analytical, moderate)         │  │   │    ║
║  │  │   └── Tier 3: Fine-tuned adapter (domain-specific)      │  │   │    ║
║  │  └── Response + token count logged to BigQuery ────────────┼──┤   │    ║
║  │       │                                                     │  │   │    ║
║  │  Guardrails (POST-generation)                               │  │   │    ║
║  │  ├── Hallucination check (grounded in context?)            │  │   │    ║
║  │  ├── PII redaction from output                             │  │   │    ║
║  │  └── Policy / compliance filter                            │  │   │    ║
║  │       │                                                     │  │   │    ║
║  │  ┌────┴─────────────────────────────┐                      │  │   │    ║
║  │  │  Response (RAG answer)           │  Workflow Execution   │  │   │    ║
║  │  │  └── write to Semantic Cache     │  ├── Action classify  │  │   │    ║
║  │  │                                  │  ├── Approval Gate    │  │   │    ║
║  │  └──────────────────────────────────┘  ├── Tool Executor    │  │   │    ║
║  │       │                               └── Audit Trail ──────┼──┤   │    ║
║  │  User receives answer                                        │  │   │    ║
║  │       │                                                     │  │   │    ║
║  │  Feedback Collection ─────────────────────────────────────→ │  │   │    ║
║  │  ├── Explicit: 👍/👎 + comment                               │  │   │    ║
║  │  └── Implicit: click-through, session length               │  │   │    ║
║  │                                                     trace end│  │   │    ║
║  │                                                     → Jaeger/  │   │    ║
║  │                                                       Cloud    │   │    ║
║  │                                                       Trace    │   │    ║
║  └─────────────────────────────────────────────────────────────┘  │   │    ║
║                                                                    │   │    ║
╠════════════════════════════════════════════════════════════════════╪═══╪════╣
║              LLMOPS PIPELINE (continuous improvement)             │   │    ║
╠════════════════════════════════════════════════════════════════════╪═══╪════╣
║                                                                    │   │    ║
║  ┌─────────────────────────────────────────────────────────────┐  │   │    ║
║  │  DATA LAYER — BigQuery (shared with enterprise RAG)         │←─┘   │    ║
║  │                                                             │←─────┘    ║
║  │  Tables:                                                    │           ║
║  │  ├── queries          (query, strategy, latency, tokens)    │           ║
║  │  ├── responses        (answer, chunks_used, model_version)  │           ║
║  │  ├── feedback         (query_id, rating, comment)           │           ║
║  │  ├── evaluations      (RAGAS metrics per strategy per run)  │           ║
║  │  └── audit_trail      (workflow actions, approvals)         │           ║
║  └─────────────────────────┬───────────────────────────────────┘           ║
║                            │                                               ║
║            ┌───────────────┼────────────────────────────┐                 ║
║            │               │                            │                 ║
║            ▼               ▼                            ▼                 ║
║  ┌──────────────┐  ┌──────────────────┐      ┌─────────────────────┐     ║
║  │  EXPERIMENT   │  │  CONTINUOUS EVAL │      │  DRIFT DETECTION    │     ║
║  │  TRACKING     │  │  PIPELINE        │      │                     │     ║
║  │               │  │                  │      │  Evidently:         │     ║
║  │  MLflow:      │  │  Argo CronWorkflow│     │  ├── Query drift     │     ║
║  │  ├── Prompt   │  │  (nightly):       │     │  │   (new query types│     ║
║  │  │  versions  │  │  ├── RAGAS eval   │     │  │   appearing?)     │     ║
║  │  ├── Strategy │  │  │   per strategy  │     │  ├── Answer drift    │     ║
║  │  │  configs   │  │  ├── Regression   │     │  │   (output dist.   │     ║
║  │  ├── Model    │  │  │   test suite    │     │  │   shifting?)      │     ║
║  │  │  versions  │  │  └── Alert if     │     │  └── Embedding drift │     ║
║  │  └── A/B test │  │      metric drops │     │      (topic shift?)  │     ║
║  │     results   │  │      below SLO    │     │           │          │     ║
║  └──────┬────────┘  └────────┬──────────┘    └─────────┬─┘          │     ║
║         │                    │                          │             │     ║
║         └────────────────────┼──────────────────────────┘             │     ║
║                              │                                         │     ║
║                              ▼                                         │     ║
║  ┌─────────────────────────────────────────────────────────────────┐  │     ║
║  │  FEEDBACK → TRAINING DATA PIPELINE                              │  │     ║
║  │                                                                 │  │     ║
║  │  Feedback Store (BigQuery)                                      │  │     ║
║  │       │                                                         │  │     ║
║  │  Curator (Argo Workflow):                                       │  │     ║
║  │  ├── Filter: keep thumbs-down with comments (most informative)  │  │     ║
║  │  ├── Dedup: remove near-identical examples                      │  │     ║
║  │  ├── Label: pair (query, bad_answer, good_answer) from expert   │  │     ║
║  │  └── Format: DPO / RLHF training format                        │  │     ║
║  │       │                                                         │  │     ║
║  │  Training Dataset (GCS)                                         │  │     ║
║  │  └── versioned, tracked in MLflow                               │  │     ║
║  └───────────────────────────┬─────────────────────────────────────┘  │     ║
║                              │                                         │     ║
║                              ▼                                         │     ║
║  ┌─────────────────────────────────────────────────────────────────┐  │     ║
║  │  FINE-TUNING PIPELINE (triggered by eval drop or drift alert)  │←─┘     ║
║  │                                                                 │        ║
║  │  Trigger conditions:                                            │        ║
║  │  ├── RAGAS faithfulness < 0.80 for 3 consecutive eval runs     │        ║
║  │  ├── User satisfaction score drops >10% week-over-week         │        ║
║  │  ├── Evidently detects >30% query drift                        │        ║
║  │  └── Manual trigger by ML engineer                             │        ║
║  │                                                                 │        ║
║  │  Pipeline (Argo Workflow on GPU node pool, KEDA scale-to-zero):│        ║
║  │  ├── Data prep: tokenize, format, split train/val              │        ║
║  │  ├── QLoRA fine-tuning (4-bit quantization + LoRA adapters)    │        ║
║  │  │   on base model (Gemini / Llama / Mistral)                  │        ║
║  │  ├── Evaluation: RAGAS on holdout set + regression suite       │        ║
║  │  └── If eval passes: register adapter in Model Registry        │        ║
║  │                                                                 │        ║
║  │  Resource management:                                           │        ║
║  │  ├── KEDA: scale GPU nodes from 0 → N when job starts          │        ║
║  │  └── KEDA: scale back to 0 when job completes (cost control)   │        ║
║  └───────────────────────────┬─────────────────────────────────────┘        ║
║                              │                                              ║
║                              ▼                                              ║
║  ┌─────────────────────────────────────────────────────────────────┐        ║
║  │  MODEL REGISTRY (MLflow Model Registry / Vertex AI Registry)   │        ║
║  │                                                                 │        ║
║  │  Tracks every version of:                                       │        ║
║  │  ├── Base model aliases:  @champion, @challenger, @baseline     │        ║
║  │  ├── LoRA adapters:       domain-specific fine-tuned adapters   │        ║
║  │  ├── Embedding models:    text-embedding-004 → custom           │        ║
║  │  └── Evaluation results attached to each version               │        ║
║  │                                                                 │        ║
║  │  Promotion workflow:                                            │        ║
║  │  ├── New adapter → @challenger (tested on 5% traffic)           │        ║
║  │  ├── If RAGAS > @champion for 48h → promote to @champion       │        ║
║  │  └── @champion always points to the live production model      │        ║
║  └───────────────────────────┬─────────────────────────────────────┘        ║
║                              │                                              ║
║                              ▼                                              ║
║  ┌─────────────────────────────────────────────────────────────────┐        ║
║  │  PROMPT REGISTRY                                                │        ║
║  │                                                                 │        ║
║  │  Version-controlled prompt templates (Git + MLflow):           │        ║
║  │  ├── system_prompt_v1, v2, v3 ...                               │        ║
║  │  ├── hyde_prompt (hypothetical document generation)             │        ║
║  │  ├── query_rewrite_prompt                                       │        ║
║  │  └── strategy-specific templates (naive / hybrid / agentic)    │        ║
║  │                                                                 │        ║
║  │  Prompt A/B testing:                                            │        ║
║  │  ├── Route X% of traffic to prompt_v2, rest to prompt_v1       │        ║
║  │  ├── Measure: RAGAS relevancy + user feedback score            │        ║
║  │  └── Argo Rollouts: canary promote or rollback                 │        ║
║  └───────────────────────────┬─────────────────────────────────────┘        ║
║                              │                                              ║
║                              ▼                                              ║
║  ┌─────────────────────────────────────────────────────────────────┐        ║
║  │  DEPLOYMENT PIPELINE (GitHub Actions + Argo Rollouts)          │        ║
║  │                                                                 │        ║
║  │  Code change / model version change:                            │        ║
║  │  ├── CI: pytest + RAGAS regression test (must pass)            │        ║
║  │  ├── Build: Docker image → Artifact Registry                    │        ║
║  │  ├── Canary deploy: 10% traffic to new version                 │        ║
║  │  ├── Analysis: error rate < 1%, RAGAS faithfulness stable      │        ║
║  │  ├── Promote: 10% → 50% → 100%                                 │        ║
║  │  └── Auto-rollback: if success_rate < 95% → revert             │        ║
║  └─────────────────────────────────────────────────────────────────┘        ║
║                                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                         OBSERVABILITY (always-on)                            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  Operational Metrics                  Quality Intelligence                   ║
║  ├── Latency P50 / P95 / P99          ├── RAGAS: faithfulness, relevancy     ║
║  ├── Error rate by component          ├── Hallucination rate trend           ║
║  ├── Token cost per query/team        ├── User satisfaction (feedback score) ║
║  ├── Cache hit / miss ratio           ├── Cache hit rate                     ║
║  ├── Retrieval recall@k               ├── Strategy A/B comparison            ║
║  ├── Model router tier distribution   └── Model version quality delta        ║
║  └── Infrastructure health                                                   ║
║          │                                          │                        ║
║          └────────────────┬─────────────────────────┘                        ║
║                           │                                                  ║
║                    Alerting + Dashboards                                      ║
║                    ├── Prometheus → Grafana (real-time ops)                  ║
║                    ├── BigQuery → Looker Studio (quality trends)             ║
║                    └── PagerDuty / Slack alerts (SLO breach)                ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## The 5 Feedback Loops Explained

### Loop 1 — Quality Loop (automated, nightly)
```
Argo CronWorkflow runs RAGAS on 50 test questions every night
  → logs to BigQuery (evaluations table)
  → if faithfulness < 0.80 for 3 consecutive nights:
      → trigger fine-tuning pipeline
      → send Slack alert to ML team
```
**Why it matters:** LLM providers quietly update model weights. Your evaluation
catches this before users notice.

### Loop 2 — Feedback Loop (event-driven)
```
User clicks 👎 on an answer + writes a comment
  → stored in BigQuery (feedback table)
  → Argo Workflow (weekly): collects 👎 examples
  → Curate: pair (query, bad_answer) with correct answer from expert
  → Fine-tune: QLoRA on curated pairs → new adapter
  → Register adapter in MLflow as @challenger
  → A/B test vs @champion → promote if better
```
**Why it matters:** The model learns from its own mistakes on your specific domain.

### Loop 3 — Cost Loop (streaming, real-time)
```
Every LLM call logs (tokens_used, model_tier, query_complexity)
  → BigQuery streaming insert
  → Grafana dashboard shows cost/query by team/namespace
  → Alert: if cost/query increases >20% week-over-week
  → Model Router adjusts routing (send more queries to Flash, fewer to Pro)
```
**Why it matters:** Token costs scale with traffic. Without this loop, you discover
overspending at month-end billing.

### Loop 4 — Experiment Loop (on-demand)
```
ML engineer wants to test new system prompt:
  1. Create prompt_v2 in Prompt Registry
  2. Argo Rollouts: route 10% traffic to prompt_v2
  3. Collect 48h of RAGAS metrics + user feedback
  4. If prompt_v2 wins: promote to 100%
  5. If loses: automatic rollback in <5 min
```
**Why it matters:** Every change to prompts, strategies, or model versions
is tested safely on live traffic before full rollout.

### Loop 5 — Drift Loop (scheduled, weekly)
```
Evidently compares this week's query embeddings vs training baseline
  → if query distribution shifted (new topics appearing):
      → alert ML team ("users now asking about X, not in training data")
      → trigger data collection: scrape relevant documents for new topic
      → re-index + update vector store
      → optional: add new topic to fine-tuning dataset
```
**Why it matters:** When your company launches a new product or enters a new market,
the RAG system's knowledge needs to update too.

---

## Tool Mapping (what runs what)

| LLMOps Component | Tool | Already in llops project? |
|---|---|---|
| Experiment tracking | MLflow | Yes (Project 05) |
| Model registry | MLflow Model Registry | Yes (@champion alias) |
| Fine-tuning pipeline | Argo Workflows + QLoRA | Yes (Project 12) |
| Scheduled eval | Argo CronWorkflow | Yes (Project 13) |
| Drift detection | Evidently | Yes (Project 11) |
| Feature store | Feast + Redis | Yes (Project 11) |
| GPU autoscaling | KEDA | Yes (Project 13) |
| Canary deployment | Argo Rollouts | Yes (Project 07) |
| CI/CD | GitHub Actions | Yes (Project 07) |
| Distributed tracing | OpenTelemetry + Jaeger | Yes (Project 10) |
| LLM gateway / routing | LiteLLM | Yes (Project 10) |
| Semantic caching | Redis (LiteLLM) | Yes (Project 10) |
| Analytics | BigQuery | This project |
| Vector search | Vertex AI Vector Search | This project |

**Every tool in this architecture is already in your llops stack.**
Enterprise RAG is the application layer. LLMOps is the operational layer.
Together they form a self-improving AI platform.

---

## When to add each LLMOps component

Start simple. Add complexity when you hit the specific pain point it solves.

| Stage | When to add it | What problem triggers it |
|---|---|---|
| Day 1 | Experiment tracking (MLflow) | "Which prompt version is live right now?" |
| Week 2 | Continuous RAGAS eval | "Did the model update break our answers?" |
| Month 1 | Semantic cache | "Token costs are too high" |
| Month 2 | Feedback collection | "Users complain but we don't know why" |
| Month 3 | Model router (cost tiers) | "Not every query needs GPT-4 Pro" |
| Month 4 | Drift detection | "New product launched, RAG doesn't know about it" |
| Month 6 | Fine-tuning pipeline | "Base model isn't good enough on our domain" |
| Month 9 | Canary deployments | "A model change broke prod last quarter" |

---

## Short reference flow (updated from original)

```
User Query
  ↓
API Gateway           ← rate limiting, TLS, OpenTelemetry trace starts
  ↓
Auth & RBAC           ← SSO / JWT / multi-tenant namespace isolation
  ↓
Conversation Memory   ← short-term (Redis) + long-term (user profile)
  ↓
Intent Router         ← prompt from Prompt Registry (versioned)
  ↓
[Semantic Cache?]     ← Redis: hit → return in <20ms, 0 tokens
  ↓ (miss)
Query Understanding   ← decompose, HyDE, expand, classify
  ↓
Hybrid Retrieval      ← Vector + BM25 + Graph + SQL + Multi-modal
  ↓
Re-ranking            ← cross-encoder + MMR + ACL filter
  ↓
Context Assembly      ← prompt template from Prompt Registry
  ↓
Guardrails (pre)      ← injection detection, PII in chunks
  ↓
LLM Generation        ← model from Model Registry (@champion)
  Model Router:         Tier 1: Gemini Flash (simple)
                        Tier 2: Gemini Pro (analytical)
                        Tier 3: Fine-tuned adapter (domain)
  ↓
Guardrails (post)     ← hallucination check, PII redact, compliance
  ↓
Response → Cache      ← write to Redis semantic cache

PARALLEL: all events → BigQuery (query, answer, tokens, latency)

  ↓
Feedback              ← 👍/👎 → BigQuery (feedback table)

═══════════════════════════════════════════════
  LLMOps loops running continuously:

  Quality Loop:    Argo CronWorkflow → RAGAS eval → MLflow
  Feedback Loop:   BigQuery → Curate → QLoRA → Model Registry
  Cost Loop:       BigQuery → Grafana → Model Router tuning
  Experiment Loop: Prompt Registry → Argo Rollouts A/B → promote
  Drift Loop:      Evidently → alert → re-index + retrain trigger
═══════════════════════════════════════════════
```
