# app/settings.py

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Dict, List # Ensure List is imported
import json, os

class Settings(BaseSettings):
    secret_key: str = "dev-secret" # Used for session cookies
    admin_password: str = "change-me-please" 

    # --- ADD THESE SSO SETTINGS ---
    oidc_tenant: str = "a10d7218-0949-401d-9396-074c40f57505"           # Your Directory (tenant) ID
    oidc_client_id: str = "6630e312-6d49-49be-9d22-781ada7b121b"        # Your Application (client) ID
    oidc_client_secret: str = ""    # Your Client Secret **Value** (Not the ID)
    oidc_redirect_uri: str = "https://attendance.sebridgeinspection.com/auth/callback"     # The callback URL (e.g., https://your-app/auth/callback)
    sso_required: bool = True       # Set to True to enable SSO
    allowed_domains: List[str] = ["sebridgeinspection.com","wsp.com","southeastbridge.onmicrosoft.com"] # Optional: List of allowed email domains
    # -----------------------------

    sites: Dict[str, str] = {"greensboro":"Greensboro","remote":"Remote"}
    default_site: str = "greensboro"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="allow")

    # --- Make sure your __init__ is still here ---
    def __init__(self, **data):
        super().__init__(**data)
        env_sites = os.getenv("SITES")
        if env_sites:
            try: self.sites = json.loads(env_sites)
            except Exception: pass
        env_allowed = os.getenv("ALLOWED_DOMAINS")
        if env_allowed:
            self.allowed_domains = [x.strip() for x in env_allowed.split(",") if x.strip()]
    # ---------------------------------------------

settings = Settings()