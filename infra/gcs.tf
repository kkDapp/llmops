# Raw document uploads
resource "google_storage_bucket" "rag_docs" {
  name          = "${var.project_id}-rag-docs"
  location      = var.region
  force_destroy = true

  versioning { enabled = true }

  lifecycle_rule {
    condition { age = 365 }
    action { type = "Delete" }
  }

  uniform_bucket_level_access = true
  depends_on = [google_project_service.apis]
}

# Processed chunks / metadata
resource "google_storage_bucket" "rag_processed" {
  name          = "${var.project_id}-rag-processed"
  location      = var.region
  force_destroy = true
  uniform_bucket_level_access = true
  depends_on = [google_project_service.apis]
}

# Pub/Sub notification: new file → trigger ingestion
resource "google_storage_notification" "new_doc" {
  bucket         = google_storage_bucket.rag_docs.name
  payload_format = "JSON_API_V1"
  topic          = google_pubsub_topic.rag_ingestion.id
  event_types    = ["OBJECT_FINALIZE"]
  depends_on     = [google_pubsub_topic_iam_member.gcs_publisher]
}
