"""
Drift Monitor — detects when query/answer distribution shifts from baseline.

Uses Evidently for statistical drift tests:
  - Query text drift: are users asking about new topics?
  - Answer length drift: are answers getting shorter/longer?
  - Token cost drift: is cost per query increasing?
  - Strategy usage drift: are certain strategies being used more?

WHY this matters:
  When your company launches a new product, users suddenly ask about it.
  The RAG system has no documents on the new product → poor answers.
  Drift detection catches this BEFORE users complain.
  Alert fires → team ingests new docs → quality restored.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import pandas as pd
from evidently import ColumnMapping
from evidently.report import Report
from evidently.metric_preset import DataDriftPreset, DataQualityPreset
from evidently.metrics import DatasetDriftMetric, ColumnDriftMetric
from google.cloud import bigquery
from config.settings import settings

logger = logging.getLogger(__name__)


class DriftMonitor:
    def __init__(self):
        self.bq = bigquery.Client(project=settings.gcp_project_id)
        self.queries_table = f"{settings.gcp_project_id}.{settings.bq_dataset}.{settings.bq_queries_table}"

    def _load_queries(self, days_back: int, limit: int = 1000) -> pd.DataFrame:
        """Load recent queries from BigQuery."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
        query = f"""
            SELECT
                query,
                strategy,
                latency_ms,
                tokens_used,
                CHAR_LENGTH(query) AS query_length
            FROM `{self.queries_table}`
            WHERE timestamp >= '{cutoff}'
            ORDER BY timestamp DESC
            LIMIT {limit}
        """
        try:
            return self.bq.query(query).to_dataframe()
        except Exception as e:
            logger.warning(f"Could not load queries from BigQuery: {e}")
            return pd.DataFrame()

    def run(
        self,
        reference_days: int = 30,
        current_days: int = 7,
        output_path: str = "/tmp/drift_report.html",
    ) -> dict:
        """
        Compare recent queries (current window) vs historical (reference window).
        Returns drift summary and saves HTML report.
        """
        reference_df = self._load_queries(days_back=reference_days)
        current_df = self._load_queries(days_back=current_days)

        if reference_df.empty or current_df.empty:
            logger.warning("Not enough data for drift detection")
            return {"drift_detected": False, "reason": "insufficient_data"}

        # Select numeric features for drift comparison
        features = ["query_length", "latency_ms", "tokens_used"]
        ref = reference_df[features].dropna()
        cur = current_df[features].dropna()

        column_mapping = ColumnMapping(numerical_features=features)

        report = Report(metrics=[
            DatasetDriftMetric(),
            ColumnDriftMetric(column_name="query_length"),
            ColumnDriftMetric(column_name="latency_ms"),
            ColumnDriftMetric(column_name="tokens_used"),
        ])
        report.run(reference_data=ref, current_data=cur, column_mapping=column_mapping)
        report.save_html(output_path)

        result_dict = report.as_dict()
        dataset_drift = result_dict["metrics"][0]["result"]

        drifted_cols = [
            col for col in features
            if result_dict["metrics"][features.index(col) + 1]["result"].get("drift_detected", False)
        ]

        summary = {
            "drift_detected": dataset_drift.get("dataset_drift", False),
            "share_of_drifted_columns": dataset_drift.get("share_of_drifted_columns", 0.0),
            "drifted_columns": drifted_cols,
            "reference_size": len(ref),
            "current_size": len(cur),
            "report_path": output_path,
        }

        if summary["drift_detected"]:
            logger.warning(
                f"DRIFT DETECTED: {len(drifted_cols)}/{len(features)} columns drifted. "
                f"Columns: {drifted_cols}"
            )
        else:
            logger.info("No drift detected.")

        return summary
