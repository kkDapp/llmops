# Redis Memorystore — semantic cache for RAG responses
resource "google_redis_instance" "rag_cache" {
  name               = "rag-semantic-cache"
  tier               = "STANDARD_HA"
  memory_size_gb     = var.redis_memory_gb
  region             = var.region
  redis_version      = "REDIS_7_0"
  display_name       = "RAG Semantic Cache"
  depends_on = [google_project_service.apis]
}
