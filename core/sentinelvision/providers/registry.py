"""Provider registry — add providers without changing core engine."""
from __future__ import annotations

from typing import Dict, List, Optional, Type

from core.sentinelvision.providers.amazon_provider import AmazonProvider
from core.sentinelvision.providers.base import ProviderBase
from core.sentinelvision.providers.cloudflare_provider import CloudflareProvider
from core.sentinelvision.providers.github_provider import GitHubProvider
from core.sentinelvision.providers.google_provider import GoogleProvider
from core.sentinelvision.providers.netlify_provider import NetlifyProvider
from core.sentinelvision.providers.resend_provider import ResendProvider
from core.sentinelvision.providers.stripe_provider import StripeProvider
from core.sentinelvision.providers.supabase_provider import SupabaseProvider

_REGISTRY: Dict[str, ProviderBase] = {}


def _register(cls: Type[ProviderBase]) -> None:
    inst = cls()
    _REGISTRY[inst.provider_id] = inst


for _cls in (
    AmazonProvider,
    SupabaseProvider,
    StripeProvider,
    CloudflareProvider,
    GitHubProvider,
    NetlifyProvider,
    GoogleProvider,
    ResendProvider,
):
    _register(_cls)


def get_provider(provider_id: str) -> Optional[ProviderBase]:
    return _REGISTRY.get((provider_id or "").lower())


def list_providers() -> List[Dict[str, str]]:
    return [{"provider_id": p.provider_id, "display_name": p.display_name} for p in _REGISTRY.values()]


def resolve_provider(objective: str) -> Optional[ProviderBase]:
    best: Optional[ProviderBase] = None
    best_score = 0.0
    for p in _REGISTRY.values():
        score = p.match_objective(objective)
        if score > best_score:
            best_score = score
            best = p
    return best if best_score >= 0.3 else None
