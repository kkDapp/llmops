import time
import logging
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from src.metrics import request_count, request_latency, active_requests

logger = logging.getLogger(__name__)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        active_requests.inc()
        try:
            response: Response = await call_next(request)
        finally:
            active_requests.dec()

        latency = time.time() - start
        strategy = request.query_params.get("strategy", "unknown")

        request_count.labels(
            method=request.method,
            endpoint=request.url.path,
            strategy=strategy,
            status=response.status_code,
        ).inc()
        request_latency.labels(
            endpoint=request.url.path,
            strategy=strategy,
        ).observe(latency)

        response.headers["X-Response-Time"] = f"{latency:.3f}s"
        return response
