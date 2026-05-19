"""
MLflow Tracker — logs every RAG query, eval run, and model version change.

Why track RAG queries in MLflow?
  Without tracking, you can't answer:
    - Which strategy performs best on which query types?
    - Did the prompt change on day 14 cause the quality drop?
    - How many tokens did namespace 'hr-team' consume this week?

MLflow experiments:
  rag-queries    → one run per query (strategy, latency, tokens, score)
  rag-eval       → one run per RAGAS evaluation (all 5 metrics)
  rag-finetune   → one run per fine-tuning job (dataset, adapter, eval delta)
  prompt-ab      → one run per prompt A/B test result
"""
import logging
import time
from contextlib import contextmanager
from typing import Optional
import mlflow
from config.settings import settings

logger = logging.getLogger(__name__)

EXPERIMENT_QUERIES   = "rag-queries"
EXPERIMENT_EVAL      = "rag-eval"
EXPERIMENT_FINETUNE  = "rag-finetune"
EXPERIMENT_PROMPT_AB = "prompt-ab"


class MLflowTracker:
    def __init__(self):
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        self._ensure_experiments()

    def _ensure_experiments(self):
        for name in [EXPERIMENT_QUERIES, EXPERIMENT_EVAL, EXPERIMENT_FINETUNE, EXPERIMENT_PROMPT_AB]:
            try:
                mlflow.set_experiment(name)
            except Exception as e:
                logger.warning(f"Could not create MLflow experiment '{name}': {e}")

    def log_query(
        self,
        query: str,
        strategy: str,
        namespace: str,
        latency_ms: float,
        tokens_used: int,
        cached: bool,
        model_tier: str,
        faithfulness_estimate: Optional[float] = None,
    ):
        try:
            mlflow.set_experiment(EXPERIMENT_QUERIES)
            with mlflow.start_run(run_name=f"{strategy}-{int(time.time())}"):
                mlflow.set_tags({
                    "strategy": strategy,
                    "namespace": namespace,
                    "model_tier": model_tier,
                    "cached": str(cached),
                })
                mlflow.log_params({
                    "query_length": len(query),
                    "strategy": strategy,
                })
                mlflow.log_metrics({
                    "latency_ms": latency_ms,
                    "tokens_used": tokens_used,
                    "cached": int(cached),
                })
                if faithfulness_estimate is not None:
                    mlflow.log_metric("faithfulness_estimate", faithfulness_estimate)
        except Exception as e:
            logger.debug(f"MLflow query log failed (non-critical): {e}")

    def log_eval(
        self,
        run_id: str,
        strategy: str,
        metrics: dict,
        num_questions: int,
        model_version: str = "unknown",
    ):
        try:
            mlflow.set_experiment(EXPERIMENT_EVAL)
            with mlflow.start_run(run_name=run_id):
                mlflow.set_tags({
                    "strategy": strategy,
                    "model_version": model_version,
                })
                mlflow.log_param("num_questions", num_questions)
                mlflow.log_metrics(metrics)
        except Exception as e:
            logger.warning(f"MLflow eval log failed: {e}")

    def log_finetune(
        self,
        run_id: str,
        base_model: str,
        dataset_version: str,
        adapter_path: str,
        eval_before: dict,
        eval_after: dict,
    ):
        try:
            mlflow.set_experiment(EXPERIMENT_FINETUNE)
            with mlflow.start_run(run_name=run_id):
                mlflow.set_tags({
                    "base_model": base_model,
                    "dataset_version": dataset_version,
                })
                mlflow.log_param("adapter_path", adapter_path)
                for k, v in eval_before.items():
                    mlflow.log_metric(f"before_{k}", v)
                for k, v in eval_after.items():
                    mlflow.log_metric(f"after_{k}", v)
                # Log improvement delta
                for k in eval_before:
                    if k in eval_after:
                        mlflow.log_metric(f"delta_{k}", eval_after[k] - eval_before[k])
        except Exception as e:
            logger.warning(f"MLflow finetune log failed: {e}")

    def register_model(self, adapter_path: str, name: str, alias: str = "challenger"):
        """Register a fine-tuned adapter in MLflow Model Registry."""
        try:
            result = mlflow.register_model(f"runs:/{adapter_path}", name)
            client = mlflow.MlflowClient()
            client.set_registered_model_alias(name, alias, result.version)
            logger.info(f"Registered model '{name}' v{result.version} as @{alias}")
            return result.version
        except Exception as e:
            logger.warning(f"Model registration failed: {e}")
            return None

    def promote_model(self, name: str, from_alias: str = "challenger", to_alias: str = "champion"):
        """Promote @challenger to @champion after eval confirms it's better."""
        try:
            client = mlflow.MlflowClient()
            version = client.get_model_version_by_alias(name, from_alias).version
            client.set_registered_model_alias(name, to_alias, version)
            logger.info(f"Promoted model '{name}' v{version}: @{from_alias} → @{to_alias}")
        except Exception as e:
            logger.warning(f"Model promotion failed: {e}")


_tracker_instance: MLflowTracker = None


def get_tracker() -> MLflowTracker:
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = MLflowTracker()
    return _tracker_instance
