# Vertex AI Vector Search Index (enterprise-scale ANN search)
# Note: index creation takes 30–90 minutes on first apply
resource "google_vertex_ai_index" "rag_index" {
  provider     = google-beta
  region       = var.region
  display_name = "rag-vector-index"
  description  = "Multi-RAG document embeddings"

  metadata {
    contents_delta_uri = "gs://${google_storage_bucket.rag_processed.name}/index-data/"
    config {
      dimensions                  = var.vector_search_dimensions
      approximate_neighbors_count = 100
      shard_size                  = "SHARD_SIZE_MEDIUM"
      distance_measure_type       = "DOT_PRODUCT_DISTANCE"
      algorithm_config {
        tree_ah_config {
          leaf_node_embedding_count    = 1000
          leaf_nodes_to_search_percent = 10
        }
      }
    }
  }

  index_update_method = "STREAM_UPDATE"
  depends_on          = [google_project_service.apis, google_storage_bucket.rag_processed]
}

# Index Endpoint — the serving endpoint for the index
resource "google_vertex_ai_index_endpoint" "rag_endpoint" {
  provider     = google-beta
  region       = var.region
  display_name = "rag-index-endpoint"
  depends_on   = [google_vertex_ai_index.rag_index]
}

# NOTE: Deploying the index requires MatchingEngineDeployedIndexNodes quota.
# Request a quota increase at: console.cloud.google.com/iam-admin/quotas
# Uncomment once quota is approved:
#
# resource "google_vertex_ai_index_endpoint_deployed_index" "rag_deployed" {
#   provider          = google-beta
#   index_endpoint    = google_vertex_ai_index_endpoint.rag_endpoint.id
#   index             = google_vertex_ai_index.rag_index.id
#   deployed_index_id = "rag_index"
#   display_name      = "rag-deployed-index"
#
#   automatic_resources {
#     min_replica_count = 1
#     max_replica_count = 5
#   }
# }

# Artifact Registry for Docker images
resource "google_artifact_registry_repository" "rag_repo" {
  location      = var.region
  repository_id = "rag-repo"
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}
