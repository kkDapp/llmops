# Service account for the RAG API pods
resource "google_service_account" "rag_api" {
  account_id   = "rag-api-sa"
  display_name = "RAG API Service Account"
}

locals {
  rag_api_roles = [
    "roles/aiplatform.user",          # Vertex AI Vector Search + Gemini
    "roles/storage.objectViewer",     # Read documents from GCS
    "roles/bigquery.dataEditor",      # Write query logs + eval results
    "roles/pubsub.publisher",         # Trigger async ingestion
    "roles/secretmanager.secretAccessor",
    "roles/cloudtrace.agent",
    "roles/monitoring.metricWriter",
    "roles/logging.logWriter",
  ]
}

resource "google_project_iam_member" "rag_api_roles" {
  for_each = toset(local.rag_api_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.rag_api.email}"
}

# Service account for the ingestion worker
resource "google_service_account" "rag_worker" {
  account_id   = "rag-worker-sa"
  display_name = "RAG Ingestion Worker Service Account"
}

locals {
  rag_worker_roles = [
    "roles/aiplatform.user",
    "roles/storage.objectAdmin",
    "roles/pubsub.subscriber",
    "roles/documentai.apiUser",
    "roles/bigquery.dataEditor",
  ]
}

resource "google_project_iam_member" "rag_worker_roles" {
  for_each = toset(local.rag_worker_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.rag_worker.email}"
}

# Workload Identity — bind K8s service accounts to GCP service accounts
resource "google_service_account_iam_member" "rag_api_workload_identity" {
  service_account_id = google_service_account.rag_api.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[default/rag-api]"
}
