import logging
from datetime import datetime, timezone
from google.cloud import bigquery
from src.api.models import EvalMetrics
from config.settings import settings

logger = logging.getLogger(__name__)


class BigQueryLogger:
    def __init__(self):
        self.client = bigquery.Client(project=settings.gcp_project_id)
        self.eval_table = f"{settings.gcp_project_id}.{settings.bq_dataset}.{settings.bq_eval_table}"
        self.queries_table = f"{settings.gcp_project_id}.{settings.bq_dataset}.{settings.bq_queries_table}"

    async def log_eval(self, run_id: str, strategy: str, metrics: EvalMetrics):
        row = {
            "run_id": run_id,
            "strategy": strategy,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "faithfulness": metrics.faithfulness,
            "answer_relevancy": metrics.answer_relevancy,
            "context_precision": metrics.context_precision,
            "context_recall": metrics.context_recall,
            "answer_correctness": metrics.answer_correctness,
        }
        errors = self.client.insert_rows_json(self.eval_table, [row])
        if errors:
            logger.error(f"BQ insert failed: {errors}")
        else:
            logger.info(f"Logged eval run {run_id} to BigQuery")

    async def log_query(self, query: str, strategy: str, latency_ms: float, tokens: int, cached: bool):
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query": query[:500],
            "strategy": strategy,
            "latency_ms": latency_ms,
            "tokens_used": tokens,
            "cached": cached,
        }
        self.client.insert_rows_json(self.queries_table, [row])

    async def get_eval_history(self, strategy: str = None, limit: int = 20) -> list[dict]:
        where = f"WHERE strategy = '{strategy}'" if strategy else ""
        query = f"""
            SELECT * FROM `{self.eval_table}`
            {where}
            ORDER BY timestamp DESC
            LIMIT {limit}
        """
        rows = list(self.client.query(query).result())
        return [dict(r) for r in rows]
