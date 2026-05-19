"""
LLMOps management endpoints — trigger and inspect the improvement pipeline.

POST /llmops/trigger-eval        → run RAGAS eval now (instead of waiting for cron)
POST /llmops/trigger-drift-check → run Evidently drift detection now
POST /llmops/trigger-finetune    → submit fine-tuning Argo workflow
GET  /llmops/model-versions      → list all model versions in MLflow registry
POST /llmops/promote-model       → promote @challenger to @champion
GET  /llmops/prompt-versions     → list prompt history from MLflow
POST /llmops/register-prompt     → register a new prompt version
"""
import logging
import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from src.llmops.mlflow_tracker import get_tracker
from src.llmops.drift_monitor import DriftMonitor
from src.prompt_registry.registry import get_registry
from src.evaluation.ragas_eval import RAGASEvaluator
from src.api.models import RAGStrategy
import mlflow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/llmops", tags=["LLMOps"])


class PromptRegisterRequest(BaseModel):
    name: str
    content: str
    author: str = "api"


class ModelPromoteRequest(BaseModel):
    model_name: str
    from_alias: str = "challenger"
    to_alias: str = "champion"


@router.post("/trigger-eval")
async def trigger_eval(strategy: RAGStrategy = RAGStrategy.hybrid, namespace: str = "default"):
    """Run RAGAS evaluation immediately and log to MLflow."""
    evaluator = RAGASEvaluator()
    tracker = get_tracker()
    try:
        metrics = await evaluator.evaluate(strategy=strategy, namespace=namespace)
        import uuid
        run_id = f"eval-{strategy.value}-{str(uuid.uuid4())[:8]}"
        tracker.log_eval(
            run_id=run_id,
            strategy=strategy.value,
            metrics=metrics.model_dump(),
            num_questions=evaluator.last_num_questions,
        )
        return {"run_id": run_id, "strategy": strategy.value, "metrics": metrics.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trigger-drift-check")
async def trigger_drift_check(reference_days: int = 30, current_days: int = 7):
    """Run Evidently drift detection and return summary."""
    monitor = DriftMonitor()
    try:
        summary = monitor.run(reference_days=reference_days, current_days=current_days)
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/model-versions")
async def list_model_versions(model_name: str = "rag-llm"):
    """List all registered model versions from MLflow Model Registry."""
    try:
        client = mlflow.MlflowClient()
        versions = client.search_model_versions(f"name='{model_name}'")
        return {
            "model_name": model_name,
            "versions": [
                {
                    "version": v.version,
                    "status": v.status,
                    "aliases": v.aliases,
                    "run_id": v.run_id,
                }
                for v in versions
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/promote-model")
async def promote_model(req: ModelPromoteRequest):
    """Promote @challenger to @champion after eval confirms improvement."""
    tracker = get_tracker()
    tracker.promote_model(req.model_name, req.from_alias, req.to_alias)
    return {
        "status": "promoted",
        "model": req.model_name,
        "from": req.from_alias,
        "to": req.to_alias,
    }


@router.get("/prompt-versions")
async def list_prompt_versions(name: str):
    """List all versions of a prompt from MLflow."""
    registry = get_registry()
    versions = registry.list_versions(name)
    return {"prompt_name": name, "versions": versions}


@router.post("/register-prompt")
async def register_prompt(req: PromptRegisterRequest):
    """Register a new prompt version. Use Argo Rollouts to A/B test before promoting."""
    registry = get_registry()
    prompt = registry.register(name=req.name, content=req.content, author=req.author)
    return {
        "name": prompt.name,
        "version": prompt.version,
        "status": "registered",
        "message": f"Prompt '{req.name}' v{prompt.version} registered. "
                   "Use /llmops/trigger-eval to measure quality before promoting to 100% traffic.",
    }


@router.get("/cost-report")
async def cost_report(days: int = 7):
    """
    Calculate actual LLM cost vs a hypothetical all-Pro baseline using MLflow run data.

    Shows:
      - Tokens consumed per model tier
      - Actual cost (with routing + caching)
      - Hypothetical cost if every query went to Gemini Pro
      - Cache savings (tokens never sent to any LLM)
      - Routing savings (Flash/fine-tuned instead of Pro)
    """
    # Prices in USD per 1M tokens (from model_router/router.py)
    PRICE_PER_M = {
        "flash":      0.075,
        "pro":        3.50,
        "fine_tuned": 0.0375,  # self-hosted vLLM marginal cost
    }
    PRO_PRICE_PER_M = 3.50

    cutoff_ms = int((time.time() - days * 86400) * 1000)

    try:
        client = mlflow.MlflowClient()
        runs = client.search_runs(
            experiment_names=["rag-queries"],
            filter_string=f"attributes.start_time >= {cutoff_ms}",
            max_results=5000,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"MLflow query failed: {e}")

    tokens_by_tier: dict[str, float] = {"flash": 0, "pro": 0, "fine_tuned": 0}
    cached_tokens: float = 0
    total_requests = len(runs)
    cached_requests = 0

    for run in runs:
        tokens = run.data.metrics.get("tokens_used", 0)
        cached = run.data.metrics.get("cached", 0)
        tier = run.data.tags.get("model_tier", "flash")

        if cached:
            cached_tokens += tokens
            cached_requests += 1
        else:
            tokens_by_tier[tier] = tokens_by_tier.get(tier, 0) + tokens

    # Actual cost (routing + caching applied)
    actual_cost_usd = sum(
        (tokens / 1_000_000) * PRICE_PER_M.get(tier, PRICE_PER_M["flash"])
        for tier, tokens in tokens_by_tier.items()
    )

    # Hypothetical: all tokens (including cached) go to Pro
    total_tokens = sum(tokens_by_tier.values()) + cached_tokens
    hypothetical_cost_usd = (total_tokens / 1_000_000) * PRO_PRICE_PER_M

    cache_savings_usd = (cached_tokens / 1_000_000) * PRO_PRICE_PER_M
    routing_savings_usd = hypothetical_cost_usd - cache_savings_usd - actual_cost_usd

    return {
        "window_days": days,
        "total_requests": total_requests,
        "cached_requests": cached_requests,
        "cache_hit_rate": round(cached_requests / max(total_requests, 1), 3),
        "tokens": {
            "by_tier": {k: int(v) for k, v in tokens_by_tier.items()},
            "cached_avoided": int(cached_tokens),
            "total_billed": int(sum(tokens_by_tier.values())),
        },
        "cost_usd": {
            "actual": round(actual_cost_usd, 4),
            "hypothetical_all_pro": round(hypothetical_cost_usd, 4),
            "saved_total": round(hypothetical_cost_usd - actual_cost_usd, 4),
            "saved_by_cache": round(cache_savings_usd, 4),
            "saved_by_routing": round(routing_savings_usd, 4),
            "reduction_pct": round(
                (1 - actual_cost_usd / max(hypothetical_cost_usd, 0.000001)) * 100, 1
            ),
        },
        "projected_monthly_savings_usd": round(
            (hypothetical_cost_usd - actual_cost_usd) / days * 30, 2
        ),
    }
