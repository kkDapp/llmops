import io
import logging
from google.cloud import storage, documentai_v1 as documentai
from pypdf import PdfReader
from config.settings import settings

logger = logging.getLogger(__name__)


class GCSLoader:
    def __init__(self):
        self.storage_client = storage.Client(project=settings.gcp_project_id)

    async def load(self, gcs_uri: str) -> list[str]:
        """Download from GCS and return list of page text strings."""
        bucket_name, blob_path = self._parse_uri(gcs_uri)
        bucket = self.storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        content = blob.download_as_bytes()

        if settings.use_document_ai:
            return await self._parse_with_document_ai(content, blob_path)
        return self._parse_locally(content, blob_path)

    def _parse_locally(self, content: bytes, path: str) -> list[str]:
        if path.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(content))
            return [page.extract_text() or "" for page in reader.pages]
        return [content.decode("utf-8", errors="replace")]

    async def _parse_with_document_ai(self, content: bytes, path: str) -> list[str]:
        client = documentai.DocumentProcessorServiceClient()
        # Use a general form parser processor
        processor_name = (
            f"projects/{settings.gcp_project_id}/locations/us/processors/general"
        )
        raw_document = documentai.RawDocument(
            content=content,
            mime_type="application/pdf" if path.endswith(".pdf") else "text/plain",
        )
        request = documentai.ProcessRequest(
            name=processor_name, raw_document=raw_document
        )
        result = client.process_document(request=request)
        return [result.document.text]

    @staticmethod
    def _parse_uri(gcs_uri: str) -> tuple[str, str]:
        without_prefix = gcs_uri.replace("gs://", "")
        parts = without_prefix.split("/", 1)
        return parts[0], parts[1]
