resource "google_container_cluster" "rag_cluster" {
  name               = "rag-cluster"
  location           = var.zone
  deletion_protection = false

  remove_default_node_pool = true
  initial_node_count       = 1

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  addons_config {
    horizontal_pod_autoscaling { disabled = false }
    http_load_balancing        { disabled = false }
  }

  depends_on = [google_project_service.apis]
}

resource "google_container_node_pool" "rag_nodes" {
  name       = "rag-node-pool"
  cluster    = google_container_cluster.rag_cluster.id
  node_count = var.gke_node_count

  node_config {
    machine_type = var.gke_machine_type
    disk_size_gb = 100

    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
    ]

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    labels = {
      env     = var.environment
      project = "rag"
    }
  }

  autoscaling {
    min_node_count = 1
    max_node_count = 10
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}
