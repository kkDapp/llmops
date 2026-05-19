import uuid
import logging
from fastapi import APIRouter, HTTPException
from src.api.models import EvalRequest, EvalResponse
from src.evaluation.ragas_eval import RAGASEvaluator
from src.evaluation.bq_logger import BigQueryLogger
from config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/evaluate", tags=["Evaluation"])

evaluator = RAGASEvaluator()
bq_logger = BigQueryLogger()


@router.post("/run", response_model=EvalResponse)
async def run_evaluation(req: EvalRequest):
    run_id = f"eval-{req.strategy.value}-{str(uuid.uuid4())[:8]}"
    try:
        metrics = await evaluator.evaluate(
            strategy=req.strategy,
            namespace=req.namespace,
            test_dataset_path=req.test_dataset_path,
        )
        await bq_logger.log_eval(run_id=run_id, strategy=req.strategy.value, metrics=metrics)
        return EvalResponse(
            strategy=req.strategy.value,
            metrics=metrics,
            num_questions=evaluator.last_num_questions,
            run_id=run_id,
        )
    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_eval_history(strategy: str = None, limit: int = 20):
    return await bq_logger.get_eval_history(strategy=strategy, limit=limit)
