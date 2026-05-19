resource "google_pubsub_topic" "rag_ingestion" {
  name       = "rag-ingestion"
  depends_on = [google_project_service.apis]
}

resource "google_pubsub_subscription" "rag_ingestion_sub" {
  name  = "rag-ingestion-sub"
  topic = google_pubsub_topic.rag_ingestion.id

  ack_deadline_seconds       = 300
  message_retention_duration = "86400s"  # 24h

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.rag_ingestion_dlq.id
    max_delivery_attempts = 5
  }
}

resource "google_pubsub_topic" "rag_ingestion_dlq" {
  name = "rag-ingestion-dlq"
}

# Allow GCS to publish to the topic
data "google_storage_project_service_account" "gcs_account" {}

resource "google_pubsub_topic_iam_member" "gcs_publisher" {
  topic  = google_pubsub_topic.rag_ingestion.id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${data.google_storage_project_service_account.gcs_account.email_address}"
}
