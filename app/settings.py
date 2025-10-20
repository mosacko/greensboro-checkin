from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Dict, List
import json, os

class Settings(BaseSettings):
    secret_key: str = "dev-secret"
    oidc_tenant: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""
    allowed_domains: List[str] = []
    sites: Dict[str, str] = {"greensboro":"Greensboro","remote":"Remote"}
    default_site: str = "greensboro"
    sso_required: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="allow")

    def __init__(self, **data):
        super().__init__(**data)
        # load sites if provided as JSON string env
        env_sites = os.getenv("SITES")
        if env_sites:
            try:
                self.sites = json.loads(env_sites)
            except Exception:
                pass
        env_allowed = os.getenv("ALLOWED_DOMAINS")
        if env_allowed:
            self.allowed_domains = [x.strip() for x in env_allowed.split(",") if x.strip()]

settings = Settings()
