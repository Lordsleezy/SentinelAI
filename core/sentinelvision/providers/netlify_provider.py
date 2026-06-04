from core.sentinelvision.providers.base import ProviderBase


class NetlifyProvider(ProviderBase):
    provider_id = "netlify"
    display_name = "Netlify"
    keywords = ("netlify", "deploy", "static site")

    def research(self, objective: str) -> dict:
        return {
            "provider": self.provider_id,
            "required_actions": [
                "Install Netlify CLI or connect Git repo",
                "Configure NETLIFY_AUTH_TOKEN",
                "Run netlify deploy or link site",
            ],
            "environment_variables": ["NETLIFY_AUTH_TOKEN"],
            "documentation": ["https://docs.netlify.com/"],
        }
