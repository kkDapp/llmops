"""
Feedback endpoint — collects user 👍/👎 on RAG answers.

This is the entry point of the Feedback Loop:
  feedback → BigQuery → weekly Argo curator job → training data → fine-tune
"""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from google.cloud import bigquery
from config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/feedback", tags=["Feedback"])

bq = bigquery.Client(project=settings.gcp_project_id)
FEEDBACK_TABLE = f"{settings.gcp_project_id}.{settings.bq_dataset}.feedback"


class FeedbackRequest(BaseModel):
    query: str = Field(..., description="The original query")
    answer: str = Field(..., description="The RAG answer that was shown")
    strategy: str
    namespace: str = "default"
    rating: int = Field(..., ge=1, le=5, description="1=terrible, 5=perfect")
    comment: str = Field(default="", max_length=1000)
    session_id: str = Field(default="", description="Optional session ID for grouping")


class FeedbackResponse(BaseModel):
    feedback_id: str
    status: str
    message: str


@router.post("/submit", response_model=FeedbackResponse)
async def submit_feedback(req: FeedbackRequest):
    """Submit user feedback on a RAG answer."""
    from uuid import uuid4
    feedback_id = str(uuid4())
    row = {
        "feedback_id": feedback_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query": req.query[:500],
        "answer": req.answer[:2000],
        "strategy": req.strategy,
        "namespace": req.namespace,
        "rating": req.rating,
        "thumbs_up": req.rating >= 4,
        "comment": req.comment,
        "session_id": req.session_id,
    }
    try:
        errors = bq.insert_rows_json(FEEDBACK_TABLE, [row])
        if errors:
            logger.error(f"BQ feedback insert failed: {errors}")
            raise HTTPException(status_code=500, detail="Failed to store feedback")
    except Exception as e:
        logger.error(f"Feedback storage error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    logger.info(f"Feedback {feedback_id}: rating={req.rating}, strategy={req.strategy}")
    return FeedbackResponse(
        feedback_id=feedback_id,
        status="stored",
        message="Thank you for your feedback",
    )


@router.get("/stats")
async def feedback_stats(namespace: str = None, days: int = 7):
    """Get feedback statistics — satisfaction score, per-strategy breakdown."""
    where = f"WHERE DATE(timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)"
    if namespace:
        where += f" AND namespace = '{namespace}'"
    query = f"""
        SELECT
            strategy,
            COUNT(*)              AS total_feedback,
            COUNTIF(thumbs_up)    AS thumbs_up,
            AVG(rating)           AS avg_rating,
            COUNTIF(rating = 1)   AS very_bad,
            COUNTIF(rating <= 2)  AS needs_improvement
        FROM `{FEEDBACK_TABLE}`
        {where}
        GROUP BY strategy
        ORDER BY avg_rating DESC
    """
    try:
        rows = list(bq.query(query).result())
        return {"days": days, "stats": [dict(r) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
