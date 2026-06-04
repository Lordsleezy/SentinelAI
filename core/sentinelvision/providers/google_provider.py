from core.sentinelvision.providers.base import ProviderBase


class GoogleProvider(ProviderBase):
    provider_id = "google"
    display_name = "Google"
    keywords = ("google", "gmail", "workspace", "cloud")

    def research(self, objective: str) -> dict:
        return {
            "provider": self.provider_id,
            "required_actions": [
                "Authenticate Google account via OAuth",
                "Complete requested Google Cloud / Workspace action",
            ],
            "environment_variables": ["GOOGLE_APPLICATION_CREDENTIALS"],
            "documentation": ["https://cloud.google.com/docs"],
        }
