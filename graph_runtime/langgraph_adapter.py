"""
LangGraph adapter for SentinelAI workflow execution.

The adapter uses LangGraph when installed and exposes a deterministic fallback
that follows the same node contract for offline/local validation.
"""

from typing import Callable, Dict

from orchestration.models import WorkflowState


try:
    from langgraph.graph import END, StateGraph  # type: ignore
except Exception:  # pragma: no cover - exercised when dependency unavailable
    END = "__end__"
    StateGraph = None


NodeHandler = Callable[[WorkflowState], WorkflowState]


class LangGraphRuntimeAdapter:
    """Builds and runs a small Sentinel workflow graph."""

    def __init__(self, nodes: Dict[str, NodeHandler]):
        self.nodes = nodes
        self.langgraph_available = StateGraph is not None
        self.graph = self._build_graph() if self.langgraph_available else None

    def _build_graph(self):
        graph = StateGraph(dict)
        for node_name, handler in self.nodes.items():
            graph.add_node(node_name, self._wrap_node(handler))
        graph.set_entry_point("route_task")
        graph.add_edge("route_task", "approval_checkpoint")
        graph.add_conditional_edges(
            "approval_checkpoint",
            self._approval_edge,
            {
                "execute": "execute_agent",
                "wait": END,
                "reject": END,
            },
        )
        graph.add_edge("execute_agent", "persist_result")
        graph.add_edge("persist_result", END)
        return graph.compile()

    def _wrap_node(self, handler: NodeHandler):
        def wrapped(state_dict):
            state = WorkflowState.from_dict(state_dict)
            return handler(state).to_dict()

        return wrapped

    def _approval_edge(self, state_dict):
        status = state_dict.get("approval_status")
        if status == "approved" or not state_dict.get("requires_approval", True):
            return "execute"
        if status == "rejected":
            return "reject"
        return "wait"

    def run(self, state: WorkflowState) -> WorkflowState:
        if self.graph is not None:
            result = self.graph.invoke(state.to_dict())
            return WorkflowState.from_dict(result)

        # Fallback keeps the same high-level graph nodes.
        state = self.nodes["route_task"](state)
        state = self.nodes["approval_checkpoint"](state)
        if state.approval_status == "approved" or not state.requires_approval:
            state = self.nodes["execute_agent"](state)
            state = self.nodes["persist_result"](state)
        return state
