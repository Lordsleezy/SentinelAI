"""Default model routing policy."""

from typing import Dict


class DefaultRoutingPolicy:
    def classify_task(self, task_type: str, prompt: str) -> str:
        text = f"{task_type} {prompt}".lower()
        if any(word in text for word in ("architecture", "deep reasoning", "complex", "critical")):
            return "high_reasoning"
        if any(word in text for word in ("code", "debug", "repo", "test", "patch")):
            return "coding"
        if any(word in text for word in ("summarize", "classify", "brief")):
            return "summarize"
        return "simple_research"

    def choose(self, registry, task_type: str, prompt: str, prefer_local: bool = True) -> Dict:
        capability = self.classify_task(task_type, prompt)
        candidates = registry.candidates_for(capability)
        if prefer_local:
            local = [item for item in candidates if item.get("local")]
            if local:
                return local[0]
        return candidates[0] if candidates else registry.list_models()["ollama_small"] | {"id": "ollama_small"}
