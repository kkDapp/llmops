resource "google_bigquery_dataset" "rag_analytics" {
  dataset_id  = "rag_analytics"
  description = "RAG system analytics — queries, evals, costs"
  location    = "US"
  depends_on  = [google_project_service.apis]
}

resource "google_bigquery_table" "queries" {
  dataset_id          = google_bigquery_dataset.rag_analytics.dataset_id
  table_id            = "queries"
  deletion_protection = false

  schema = jsonencode([
    { name = "timestamp",  type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "query",      type = "STRING",    mode = "REQUIRED" },
    { name = "strategy",   type = "STRING",    mode = "REQUIRED" },
    { name = "namespace",  type = "STRING",    mode = "NULLABLE" },
    { name = "latency_ms", type = "FLOAT",     mode = "NULLABLE" },
    { name = "tokens_used",type = "INTEGER",   mode = "NULLABLE" },
    { name = "cached",     type = "BOOLEAN",   mode = "NULLABLE" },
  ])

  time_partitioning {
    type  = "DAY"
    field = "timestamp"
  }

  lifecycle {
    ignore_changes = all
  }
}

resource "google_bigquery_table" "evaluations" {
  dataset_id          = google_bigquery_dataset.rag_analytics.dataset_id
  table_id            = "evaluations"
  deletion_protection = false

  schema = jsonencode([
    { name = "run_id",             type = "STRING",  mode = "REQUIRED" },
    { name = "strategy",           type = "STRING",  mode = "REQUIRED" },
    { name = "timestamp",          type = "TIMESTAMP",mode = "REQUIRED"},
    { name = "faithfulness",       type = "FLOAT",   mode = "NULLABLE" },
    { name = "answer_relevancy",   type = "FLOAT",   mode = "NULLABLE" },
    { name = "context_precision",  type = "FLOAT",   mode = "NULLABLE" },
    { name = "context_recall",     type = "FLOAT",   mode = "NULLABLE" },
    { name = "answer_correctness", type = "FLOAT",   mode = "NULLABLE" },
  ])

  time_partitioning {
    type  = "DAY"
    field = "timestamp"
  }

  lifecycle {
    ignore_changes = all
  }
}
