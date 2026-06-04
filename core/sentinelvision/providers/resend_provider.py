from core.sentinelvision.providers.base import ProviderBase


class ResendProvider(ProviderBase):
    provider_id = "resend"
    display_name = "Resend"
    keywords = ("resend", "email", "transactional")

    def research(self, objective: str) -> dict:
        return {
            "provider": self.provider_id,
            "required_actions": [
                "Create Resend API key",
                "Configure RESEND_API_KEY",
                "Verify sending domain",
            ],
            "environment_variables": ["RESEND_API_KEY"],
            "documentation": ["https://resend.com/docs"],
        }
