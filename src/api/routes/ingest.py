import uuid
import logging
from fastapi import APIRouter, HTTPException, UploadFile, File
from google.cloud import storage, pubsub_v1
import json
from src.api.models import IngestRequest, IngestResponse
from src.ingestion.gcs_loader import GCSLoader
from src.ingestion.chunkers import ChunkerFactory
from src.ingestion.embedder import VertexEmbedder
from src.retrieval.vector_store import VectorStore
from config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ingest", tags=["Ingestion"])

loader = GCSLoader()
embedder = VertexEmbedder()
vector_store = VectorStore()


@router.post("/gcs", response_model=IngestResponse)
async def ingest_from_gcs(req: IngestRequest):
    """Trigger synchronous ingestion of a GCS document."""
    doc_id = str(uuid.uuid4())
    try:
        # Load and parse
        pages = await loader.load(req.gcs_uri)
        # Chunk
        chunker = ChunkerFactory.get("recursive")
        chunks = chunker.chunk(pages, doc_id=doc_id, metadata=req.metadata)
        # Embed
        chunks_with_embeddings = await embedder.embed_chunks(chunks)
        # Store
        await vector_store.upsert(chunks_with_embeddings, namespace=req.namespace)
        return IngestResponse(
            document_id=doc_id,
            chunks_created=len(chunks),
            status="success",
            message=f"Ingested {len(pages)} pages into {len(chunks)} chunks",
        )
    except Exception as e:
        logger.error(f"Ingest failed for {req.gcs_uri}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload", response_model=IngestResponse)
async def ingest_upload(
    file: UploadFile = File(...),
    namespace: str = "default",
):
    """Upload a file directly, store to GCS, then ingest."""
    doc_id = str(uuid.uuid4())
    gcs_uri = f"gs://{settings.gcs_bucket_name}/uploads/{doc_id}/{file.filename}"

    client = storage.Client(project=settings.gcp_project_id)
    bucket = client.bucket(settings.gcs_bucket_name)
    blob = bucket.blob(f"uploads/{doc_id}/{file.filename}")

    content = await file.read()
    blob.upload_from_string(content, content_type=file.content_type)

    req = IngestRequest(gcs_uri=gcs_uri, namespace=namespace)
    return await ingest_from_gcs(req)


@router.post("/trigger-async")
async def trigger_async_ingest(req: IngestRequest):
    """Publish to Pub/Sub for async background ingestion."""
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(settings.gcp_project_id, settings.pubsub_topic)
    message = json.dumps({"gcs_uri": req.gcs_uri, "namespace": req.namespace}).encode()
    future = publisher.publish(topic_path, message)
    msg_id = future.result()
    return {"status": "queued", "message_id": msg_id, "gcs_uri": req.gcs_uri}
