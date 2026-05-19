variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "GCP zone"
  type        = string
  default     = "us-central1-a"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "gke_node_count" {
  description = "Number of GKE nodes"
  type        = number
  default     = 2
}

variable "gke_machine_type" {
  description = "GKE node machine type"
  type        = string
  default     = "n2-standard-4"
}

variable "vector_search_dimensions" {
  description = "Embedding dimensions (must match embedding model output)"
  type        = number
  default     = 768
}

variable "redis_memory_gb" {
  description = "Redis Memorystore memory in GB"
  type        = number
  default     = 1
}

variable "docker_image" {
  description = "Docker image for RAG API (e.g. YOUR_USERNAME/rag-api:latest)"
  type        = string
  default     = "gcr.io/PROJECT_ID/rag-api:latest"
}
