from core.sentinelvision.providers.base import ProviderBase


class StripeProvider(ProviderBase):
    provider_id = "stripe"
    display_name = "Stripe"
    keywords = ("stripe", "payment", "checkout", "billing")

    def research(self, objective: str) -> dict:
        return {
            "provider": self.provider_id,
            "required_actions": [
                "Create Stripe account or use existing dashboard",
                "Generate restricted API keys (publishable + secret)",
                "Configure STRIPE_SECRET_KEY and STRIPE_PUBLISHABLE_KEY",
                "Create product/price if selling items",
                "Set up webhook endpoint for payment events",
            ],
            "environment_variables": ["STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_WEBHOOK_SECRET"],
            "documentation": ["https://docs.stripe.com/get-started"],
        }

    def execute(self, step: dict, operators) -> dict:
        from core.sentinelvision.providers.workflows import get_workflow_runner
        return get_workflow_runner().execute_step(self.provider_id, step, operators)

    def verify(self, objective: str, context: dict) -> dict:
        from core.sentinelvision.providers.workflows import get_workflow_runner
        return get_workflow_runner().verify_autonomous(self.provider_id, objective, context)
