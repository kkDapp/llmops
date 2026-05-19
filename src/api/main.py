import logging
import vertexai
import google.generativeai as genai
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from prometheus_client import make_asgi_app
from src.api.middleware import MetricsMiddleware
from config.settings import settings

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

# Init both SDKs before route imports — routes instantiate clients at module level
vertexai.init(project=settings.gcp_project_id, location=settings.vertex_ai_location)
genai.configure(api_key=settings.gemini_api_key)

from src.api.routes import rag, ingest, eval as eval_router, feedback, llmops  # noqa: E402
from src.prompt_registry.registry import get_registry  # noqa: E402
from src.model_router.router import get_router  # noqa: E402

app = FastAPI(
    title="Enterprise Multi-RAG + LLMOps API",
    description="Enterprise RAG with 5 strategies + LLMOps continuous improvement on GCP",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(MetricsMiddleware)

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
app.mount("/static", StaticFiles(directory="static"), name="static")

# RAG routes
app.include_router(rag.router)
app.include_router(ingest.router)
app.include_router(eval_router.router)

# LLMOps routes
app.include_router(feedback.router)
app.include_router(llmops.router)


@app.on_event("startup")
async def startup():
    vertexai.init(project=settings.gcp_project_id, location=settings.vertex_ai_location)
    genai.configure(api_key=settings.gemini_api_key)
    get_registry()   # warm up prompt registry
    get_router()     # warm up model router
    logger.info(f"Enterprise Multi-RAG + LLMOps API started | project={settings.gcp_project_id}")


@app.get("/")
async def ui():
    return FileResponse("static/index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    return {
        "status": "ready",
        "strategies": ["naive", "advanced", "hybrid", "graph", "agentic"],
        "llmops": ["feedback", "eval", "drift-check", "model-registry", "prompt-registry"],
    }
