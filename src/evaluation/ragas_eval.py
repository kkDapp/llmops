import json
import logging
import os
from pathlib import Path
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
    answer_correctness,
)
from src.retrieval.naive import NaiveRetriever
from src.retrieval.advanced import AdvancedRetriever
from src.retrieval.hybrid import HybridRetriever
from src.retrieval.graph import GraphRetriever
from src.retrieval.agentic import AgenticRetriever
from src.generation.gemini import GeminiClient
from src.api.models import RAGStrategy, EvalMetrics

logger = logging.getLogger(__name__)

DEFAULT_DATASET = Path(__file__).parent / "test_dataset.json"

RETRIEVERS = {
    RAGStrategy.naive: NaiveRetriever,
    RAGStrategy.advanced: AdvancedRetriever,
    RAGStrategy.hybrid: HybridRetriever,
    RAGStrategy.graph: GraphRetriever,
    RAGStrategy.agentic: AgenticRetriever,
}


class RAGASEvaluator:
    def __init__(self):
        self.gemini = GeminiClient()
        self.last_num_questions = 0

    async def evaluate(
        self,
        strategy: RAGStrategy,
        namespace: str = "default",
        test_dataset_path: str = None,
    ) -> EvalMetrics:
        dataset_path = test_dataset_path or str(DEFAULT_DATASET)
        with open(dataset_path) as f:
            test_data = json.load(f)

        self.last_num_questions = len(test_data)
        retriever = RETRIEVERS[strategy](namespace=namespace)

        questions, answers, contexts, ground_truths = [], [], [], []
        for item in test_data:
            query = item["question"]
            chunks = await retriever.retrieve(query, top_k=5)
            answer, _ = await self.gemini.generate(query, chunks, strategy)

            questions.append(query)
            answers.append(answer)
            contexts.append([c.text for c in chunks])
            ground_truths.append(item.get("ground_truth", ""))

        dataset = Dataset.from_dict({
            "question": questions,
            "answer": answers,
            "contexts": contexts,
            "ground_truth": ground_truths,
        })

        result = evaluate(
            dataset,
            metrics=[faithfulness, answer_relevancy, context_precision, context_recall, answer_correctness],
        )

        return EvalMetrics(
            faithfulness=round(float(result["faithfulness"]), 4),
            answer_relevancy=round(float(result["answer_relevancy"]), 4),
            context_precision=round(float(result["context_precision"]), 4),
            context_recall=round(float(result["context_recall"]), 4),
            answer_correctness=round(float(result["answer_correctness"]), 4),
        )
