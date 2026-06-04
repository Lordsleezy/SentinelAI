from core.sentinelvision.providers.base import ProviderBase


class AmazonProvider(ProviderBase):
    provider_id = "amazon"
    display_name = "Amazon"
    keywords = ("amazon", "buy", "order", "purchase", "spatula", "prime")

    def research(self, objective: str) -> dict:
        return {
            "provider": self.provider_id,
            "required_actions": [
                "Search Amazon for product matching user objective",
                "Filter by rating (4+ stars) and Prime eligibility if preferred",
                "Compare price and shipping ETA",
                "Present best option to user for approval",
                "Complete checkout after explicit purchase approval",
                "Store order confirmation and receipt artifact",
            ],
            "requires_approval": True,
            "documentation": [],
        }

    def execute(self, step: dict, operators) -> dict:
        from core.sentinelvision.providers.workflows import get_workflow_runner
        return get_workflow_runner().execute_step(self.provider_id, step, operators)

    def verify(self, objective: str, context: dict) -> dict:
        from core.sentinelvision.providers.workflows import get_workflow_runner
        return get_workflow_runner().verify_autonomous(self.provider_id, objective, context)
