"""
Full Orchestration Pipeline — Coordinates all components for end-to-end task execution
"""
import os
import json
import logging
import uuid
import threading
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

CAPABILITY_DESCRIPTION = "Orchestrates complete task pipeline with decomposition, routing, and execution"

from .task_decomposer import get_decomposer
from .confidence import get_confidence_wrapper
from .verifier import get_verifier
from .chain_of_thought import get_cot
from .rag import get_rag
from .model_selector import get_model_selector


class OrchestrationPipeline:
    """Coordinates all orchestration components"""

    def __init__(self):
        self.decomposer = get_decomposer()
        self.confidence = get_confidence_wrapper()
        self.verifier = get_verifier()
        self.cot = get_cot()
        self.rag = get_rag()
        self.selector = get_model_selector()

        self.pending_plans = {}  # plan_id -> plan
        self.execution_results = {}  # plan_id -> results

        # Start RAG indexing in background
        threading.Thread(target=self._background_index, daemon=True).start()

    def _background_index(self):
        """Index codebase in background"""
        try:
            logger.info("Starting background RAG indexing")
            self.rag.index_codebase()
            logger.info("RAG indexing complete")
        except Exception as e:
            logger.error(f"Background indexing failed: {e}")

    def process(self, user_request: str, plan_id: Optional[str] = None) -> Dict[str, Any]:
        """Process user request through full pipeline"""

        # Step 1: Generate or retrieve plan
        if plan_id and plan_id in self.pending_plans:
            plan = self.pending_plans[plan_id]
        else:
            plan_id = str(uuid.uuid4())[:8]
            plan = self.decomposer.generate_plan(user_request)
            plan["plan_id"] = plan_id

        # Step 2: Return plan for approval if complex
        if plan["complexity"] == "complex":
            self.pending_plans[plan_id] = plan
            return {
                "type": "plan_preview",
                "plan_id": plan_id,
                "plan": plan,
                "message": "Complex task detected - review the plan below before executing"
            }

        # Step 3: Execute approved/simple plan
        results = self._execute_plan(plan)

        # Step 4: Assemble response
        final_response = self._assemble_response(user_request, plan, results)

        # Cleanup
        if plan_id in self.pending_plans:
            del self.pending_plans[plan_id]

        return {
            "type": "execution_complete",
            "plan_id": plan_id,
            "response": final_response,
            "results": results
        }

    def _execute_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Execute all subtasks in plan"""
        results = {
            "plan_id": plan.get("plan_id"),
            "original_request": plan.get("original_request"),
            "subtasks": []
        }

        for subtask in plan.get("subtasks", []):
            result = self._execute_subtask(subtask)
            results["subtasks"].append(result)

        return results

    def _execute_subtask(self, subtask: Dict[str, Any]) -> Dict[str, Any]:
        """Execute single subtask with full pipeline"""
        task = subtask["task"]
        task_type = subtask["type"]
        complexity = "COMPLEX" if len(task) > 100 else "SIMPLE"

        result = {
            "index": subtask["index"],
            "task": task,
            "type": task_type,
            "status": "executing"
        }

        try:
            # Get context from RAG
            context = self.rag.get_context_for_task(task)

            # Select model
            model_info = self.selector.select(task, task_type, complexity)

            # Apply COT for complex code tasks
            final_prompt = task
            if task_type in ["CODE", "FILE"] and complexity == "COMPLEX":
                final_prompt = self.cot.apply_cot_prefix(task, task_type, context)

            # Execute with confidence scoring
            execution_result = self.confidence.call_with_fallback(final_prompt, context)

            result["response"] = execution_result.get("response", "")
            result["model"] = execution_result.get("model", "unknown")
            result["confidence"] = execution_result.get("confidence", "MEDIUM")
            result["escalated"] = execution_result.get("escalated", False)

            # Verify result
            verification = self.verifier.verify(task, str(execution_result), task_type)
            result["verified"] = verification.get("passed", True)
            result["status"] = "completed"

        except Exception as e:
            logger.error(f"Subtask {subtask['index']} failed: {e}")
            result["status"] = "failed"
            result["error"] = str(e)

        return result

    def _assemble_response(
        self,
        original_request: str,
        plan: Dict[str, Any],
        results: Dict[str, Any]
    ) -> str:
        """Assemble final natural language response"""

        subtask_results = results.get("subtasks", [])

        if not subtask_results:
            return "No results to assemble"

        # Build summary
        summary_parts = []

        for result in subtask_results:
            if result.get("status") == "completed":
                summary_parts.append(f"- {result['task']}: ✓ {result.get('response', 'completed')[:100]}")
            elif result.get("status") == "failed":
                summary_parts.append(f"- {result['task']}: ✗ {result.get('error', 'failed')}")

        assembled = f"""Based on your request: "{original_request}"

Results:
{chr(10).join(summary_parts)}

"""

        if len(subtask_results) == 1 and subtask_results[0].get("response"):
            # Single task - return response directly
            return subtask_results[0].get("response", assembled)

        return assembled

    def approve_plan(self, plan_id: str) -> Dict[str, Any]:
        """Approve a pending plan and execute it"""
        if plan_id not in self.pending_plans:
            return {"error": "Plan not found"}

        plan = self.pending_plans[plan_id]
        results = self._execute_plan(plan)

        final_response = self._assemble_response(
            plan.get("original_request"),
            plan,
            results
        )

        # Cleanup
        del self.pending_plans[plan_id]

        return {
            "type": "execution_complete",
            "plan_id": plan_id,
            "response": final_response,
            "results": results
        }

    def deny_plan(self, plan_id: str) -> Dict[str, Any]:
        """Deny a pending plan"""
        if plan_id not in self.pending_plans:
            return {"error": "Plan not found"}

        del self.pending_plans[plan_id]

        return {
            "type": "plan_denied",
            "plan_id": plan_id,
            "message": "Plan was cancelled"
        }

    def get_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Get pending plan details"""
        return self.pending_plans.get(plan_id)

    def get_pending_plans(self) -> List[Dict[str, Any]]:
        """Get all pending plans"""
        return list(self.pending_plans.values())

    def get_status(self) -> Dict[str, Any]:
        """Get pipeline status"""
        return {
            "pending_plans": len(self.pending_plans),
            "rag_status": self.rag.get_status(),
            "available_models": self.selector.list_available_tiers(),
            "decomposer": "ready",
            "confidence_wrapper": "ready",
            "verifier": "ready"
        }

    def test(self) -> Dict[str, Any]:
        """Test the full pipeline"""
        test_request = "Write a Python function that adds two numbers and returns the sum"

        try:
            result = self.process(test_request)
            return {
                "success": True,
                "test_request": test_request,
                "result": result
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


# Global instance
_pipeline = None


def get_pipeline() -> OrchestrationPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = OrchestrationPipeline()
    return _pipeline
