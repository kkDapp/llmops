"""
Cloud Run Job / Pub/Sub subscriber for async document ingestion.
Triggered when a new file is uploaded to GCS.
"""
import asyncio
import json
import logging
import os
from google.cloud import pubsub_v1
from src.ingestion.gcs_loader import GCSLoader
from src.ingestion.chunkers import ChunkerFactory
from src.ingestion.embedder import VertexEmbedder
from src.retrieval.vector_store import VectorStore
from config.settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

loader = GCSLoader()
embedder = VertexEmbedder()
vector_store = VectorStore()


async def process_message(message_data: dict):
    gcs_uri = message_data.get("gcs_uri") or (
        f"gs://{message_data.get('bucket', '')}/{message_data.get('name', '')}"
    )
    namespace = message_data.get("namespace", "default")
    logger.info(f"Processing: {gcs_uri} → namespace={namespace}")

    pages = await loader.load(gcs_uri)
    chunker = ChunkerFactory.get("recursive")
    chunks = chunker.chunk(pages, doc_id=gcs_uri.split("/")[-1])
    embedded = await embedder.embed_chunks(chunks)
    await vector_store.upsert(embedded, namespace=namespace)
    logger.info(f"Ingested {len(embedded)} chunks from {gcs_uri}")


def callback(message):
    data = json.loads(message.data.decode("utf-8"))
    asyncio.run(process_message(data))
    message.ack()


def main():
    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(
        settings.gcp_project_id, settings.pubsub_subscription
    )
    logger.info(f"Listening on {subscription_path}")
    streaming_pull = subscriber.subscribe(subscription_path, callback=callback)
    with subscriber:
        try:
            streaming_pull.result()
        except KeyboardInterrupt:
            streaming_pull.cancel()


if __name__ == "__main__":
    main()
