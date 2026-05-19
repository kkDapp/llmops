from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # GCP
    gcp_project_id: str = "your-project-id"
    gcp_region: str = "us-central1"
    gcp_zone: str = "us-central1-a"

    # GCS
    gcs_bucket_name: str = "rag-docs"
    gcs_processed_bucket: str = "rag-processed"

    # Vertex AI
    vertex_ai_location: str = "us-central1"
    embedding_model: str = "text-embedding-004"
    embedding_dimensions: int = 768
    gemini_api_key: str = ""
    llm_model_flash: str = "gemini-2.5-flash"
    llm_model_pro: str = "gemini-2.5-pro"
    vector_search_index_id: str = ""
    vector_search_endpoint_id: str = ""

    # BigQuery
    bq_dataset: str = "rag_analytics"
    bq_queries_table: str = "queries"
    bq_eval_table: str = "evaluations"

    # Pub/Sub
    pubsub_topic: str = "rag-ingestion"
    pubsub_subscription: str = "rag-ingestion-sub"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    cache_ttl_seconds: int = 3600

    # ChromaDB (local dev)
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    chroma_collection: str = "rag_documents"

    # LLMOps
    mlflow_tracking_uri: str = "http://localhost:5000"
    mlflow_experiment_queries: str = "rag-queries"
    mlflow_experiment_eval: str = "rag-eval"
    mlflow_experiment_finetune: str = "rag-finetune"
    model_registry_name: str = "rag-llm"
    fine_tuned_available: bool = False   # True once first adapter is trained + registered
    vllm_adapter_endpoint: str = ""     # vLLM endpoint serving the LoRA adapter

    # Feature flags
    use_vertex_vector_search: bool = False
    use_document_ai: bool = False
    use_semantic_cache: bool = True
    enable_guardrails: bool = True
    enable_mlflow_logging: bool = True
    enable_reranker: bool = True       # cross-encoder reranking (adds ~200ms on CPU)
    enable_verification: bool = False  # answer verification (adds ~1 LLM call per request)
    rerank_candidate_multiplier: int = 10  # retrieve top_k * this, then rerank to top_k
    rerank_max_candidates: int = 50    # cap to avoid O(n) cross-encoder blowup

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
