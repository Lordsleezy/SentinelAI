from core.sentinelvision.providers.base import ProviderBase


class CloudflareProvider(ProviderBase):
    provider_id = "cloudflare"
    display_name = "Cloudflare"
    keywords = ("cloudflare", "dns", "cdn", "domain", "renew")

    def research(self, objective: str) -> dict:
        return {
            "provider": self.provider_id,
            "required_actions": [
                "Log in to Cloudflare dashboard",
                "Select zone / domain",
                "Update DNS records or SSL/TLS settings as needed",
                "Renew domain registration if objective mentions renew",
            ],
            "environment_variables": ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ZONE_ID"],
            "documentation": ["https://developers.cloudflare.com/fundamentals/api/"],
        }
