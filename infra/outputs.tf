output "kubectl_command" {
  value = "gcloud container clusters get-credentials rag-cluster --zone ${var.zone} --project ${var.project_id}"
}

output "gcs_docs_bucket" {
  value = google_storage_bucket.rag_docs.name
}

output "redis_host" {
  value = google_redis_instance.rag_cache.host
}

output "vector_search_index_id" {
  value = google_vertex_ai_index.rag_index.id
}

output "vector_search_endpoint_id" {
  value = google_vertex_ai_index_endpoint.rag_endpoint.id
}

output "artifact_registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/rag-repo"
}

output "bq_dataset" {
  value = google_bigquery_dataset.rag_analytics.dataset_id
}
