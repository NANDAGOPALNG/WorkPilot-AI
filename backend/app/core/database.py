from functools import lru_cache

from supabase import Client, create_client

from app.core.config import get_settings


@lru_cache
def get_supabase() -> Client:
    """Return the shared Supabase client (service-role, backend only).

    Raises ConfigError if SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are missing or invalid.
    """
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
