from core.sentinelvision.providers.base import ProviderBase


class GitHubProvider(ProviderBase):
    provider_id = "github"
    display_name = "GitHub"
    keywords = ("github", "repository", "repo", "push", "deploy")

    def research(self, objective: str) -> dict:
        return {
            "provider": self.provider_id,
            "required_actions": [
                "Authenticate with GitHub (PAT or OAuth)",
                "Create or select repository",
                "Push code / configure Actions workflow if deploy",
            ],
            "environment_variables": ["GITHUB_TOKEN"],
            "documentation": ["https://docs.github.com/en/authentication"],
        }
