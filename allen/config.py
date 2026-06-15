from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Auth — shared key required on /draft, /speak, /listen (blank = open).
    allen_api_key: str = ""
    admin_api_key: str = ""  # mints per-project API keys via POST /projects

    # Platform data layer (projects + namespaced memory). Blank = stateless mode.
    database_url: str = ""

    # ALLEN I VERSE console — Google sign-in (single authorized user) + session cookie.
    google_client_id: str = ""
    auth_allowed_email: str = ""
    cookie_secret: str = ""

    # LLM
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-sonnet-latest"  # override via env to current model

    # Speech
    elevenlabs_api_key: str = ""
    allen_voice_id: str = "Z3Gpg2pTWuj7g4RFQM9J"  # COM Coach Rahm
    openai_api_key: str = ""  # optional, for Whisper STT

    # Google Drive (script drafts → Google Docs)
    gdrive_client_id: str = ""
    gdrive_client_secret: str = ""
    gdrive_refresh_token: str = ""
    gdrive_scripts_folder_id: str = ""

    # Operational data sources for ALLIE (project mgmt + knowledge base)
    clickup_api_token: str = ""
    clickup_team_id: str = ""
    notion_api_key: str = ""
    # AMG (Cappo's domain) is its own system; flip on when Cappo matures under ALLIE.
    allie_amg_enabled: bool = False

    # Cappo — the AMG operations AI, reachable by ALLIE's delegate_to_cappo (keyed M2M call).
    cappo_agent_url: str = "https://cappo.apex-meridian-group.com/api/agent"
    cappo_agent_key: str = ""

    # Google Calendar — ALLEN's personal calendar CRUD (OAuth refresh token).
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_calendar_refresh_token: str = ""
    google_calendar_id: str = "primary"
    google_oauth_redirect: str = "https://allen.i.verse.rmasters.group/oauth/calendar/callback"

    port: int = 8090

    @property
    def clickup_ready(self) -> bool:
        return bool(self.clickup_api_token)

    @property
    def notion_ready(self) -> bool:
        return bool(self.notion_api_key)

    @property
    def cappo_ready(self) -> bool:
        return bool(self.cappo_agent_url and self.cappo_agent_key)

    @property
    def calendar_ready(self) -> bool:
        return bool(
            self.google_oauth_client_id and self.google_oauth_client_secret and self.google_calendar_refresh_token
        )

    @property
    def llm_ready(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def tts_ready(self) -> bool:
        return bool(self.elevenlabs_api_key)

    @property
    def stt_ready(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def docs_ready(self) -> bool:
        return bool(
            self.gdrive_client_id
            and self.gdrive_client_secret
            and self.gdrive_refresh_token
            and self.gdrive_scripts_folder_id
        )


settings = Settings()
