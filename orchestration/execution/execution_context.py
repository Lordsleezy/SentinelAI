"""Build persistent execution context for workflow runs."""

from typing import Dict

from model_router import get_model_router
from retrieval import SemanticRetriever


class ExecutionContextBuilder:
    def __init__(self):
        self.retriever = SemanticRetriever()

    def build(self, workflow_state: Dict) -> Dict:
        goal = workflow_state.get("goal", "")
        memories = self.retriever.retrieve(
            goal,
            ["workflow", "execution", "project", "codebase", "research"],
            limit_per_namespace=3,
        )
        model = get_model_router().route(workflow_state.get("workflow_type", "general"), goal)
        return {
            "relevant_memory": memories[:10],
            "model_route": model,
        }
