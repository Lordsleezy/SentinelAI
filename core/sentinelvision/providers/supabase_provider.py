from core.sentinelvision.providers.base import ProviderBase


class SupabaseProvider(ProviderBase):
    provider_id = "supabase"
    display_name = "Supabase"
    keywords = ("supabase", "postgres", "database project")

    def research(self, objective: str) -> dict:
        return {
            "provider": self.provider_id,
            "required_actions": [
                "Create Supabase project at https://supabase.com/dashboard",
                "Copy SUPABASE_URL and SUPABASE_ANON_KEY from project settings",
                "Configure environment variables in application",
                "Run database migrations or SQL schema if required",
                "Enable Row Level Security policies as needed",
            ],
            "environment_variables": ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"],
            "documentation": ["https://supabase.com/docs/guides/getting-started"],
        }

    def execute(self, step: dict, operators) -> dict:
        from core.sentinelvision.providers.workflows import get_workflow_runner
        return get_workflow_runner().execute_step(self.provider_id, step, operators)

    def verify(self, objective: str, context: dict) -> dict:
        from core.sentinelvision.providers.workflows import get_workflow_runner
        return get_workflow_runner().verify_autonomous(self.provider_id, objective, context)
