# LLMOps infrastructure additions

# GPU node pool for fine-tuning (KEDA scales this from 0 → 1 → 0)
resource "google_container_node_pool" "gpu_nodes" {
  name    = "gpu-node-pool"
  cluster = google_container_cluster.rag_cluster.id

  initial_node_count = 0

  node_config {
    machine_type = "n1-standard-4"

    guest_accelerator {
      type  = "nvidia-tesla-t4"
      count = 1
      gpu_driver_installation_config {
        gpu_driver_version = "DEFAULT"
      }
    }

    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]

    taint {
      key    = "nvidia.com/gpu"
      value  = "present"
      effect = "NO_SCHEDULE"
    }

    labels = {
      env  = var.environment
      role = "gpu-finetune"
    }
  }

  autoscaling {
    min_node_count = 0
    max_node_count = 2
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}

# Feedback table in BigQuery (LLMOps feedback loop)
resource "google_bigquery_table" "feedback" {
  dataset_id          = google_bigquery_dataset.rag_analytics.dataset_id
  table_id            = "feedback"
  deletion_protection = false

  schema = jsonencode([
    { name = "feedback_id", type = "STRING",    mode = "REQUIRED" },
    { name = "timestamp",   type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "query",       type = "STRING",    mode = "REQUIRED" },
    { name = "answer",      type = "STRING",    mode = "NULLABLE" },
    { name = "strategy",    type = "STRING",    mode = "NULLABLE" },
    { name = "namespace",   type = "STRING",    mode = "NULLABLE" },
    { name = "rating",      type = "INTEGER",   mode = "REQUIRED" },
    { name = "thumbs_up",   type = "BOOLEAN",   mode = "NULLABLE" },
    { name = "comment",     type = "STRING",    mode = "NULLABLE" },
    { name = "session_id",  type = "STRING",    mode = "NULLABLE" },
  ])

  time_partitioning {
    type  = "DAY"
    field = "timestamp"
  }

  lifecycle {
    ignore_changes = all
  }
}

# Secret Manager secrets for LLMOps config
resource "google_secret_manager_secret" "mlflow_tracking_uri" {
  secret_id = "mlflow-tracking-uri"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "mlflow_tracking_uri" {
  secret      = google_secret_manager_secret.mlflow_tracking_uri.id
  secret_data = "http://mlflow.default.svc.cluster.local:5000"
}

# IAM grants for Argo workflow SA are applied after Argo Workflows is deployed to GKE
# (the argo SA is created by the Argo Workflows Helm chart, not by Terraform)
