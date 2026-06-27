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
    anthropic_model: str = "claude-sonnet-4-6"  # override via env; pick per-message in the console

    # Attachments — multi-file staging
    max_attach_files: int = 5        # max files per chat turn
    max_upload_bytes: int = 52_428_800  # 50 MB per file

    # Speech
    elevenlabs_api_key: str = ""
    allen_voice_id: str = "Z3Gpg2pTWuj7g4RFQM9J"  # COM Coach Rahm
    openai_api_key: str = ""  # optional, for Whisper STT

    # Google Drive (script drafts → Google Docs + YouTube media archive)
    gdrive_client_id: str = ""
    gdrive_client_secret: str = ""
    gdrive_refresh_token: str = ""
    gdrive_scripts_folder_id: str = ""
    gdrive_youtube_folder_id: str = ""  # Drive folder for YouTube audio/video/transcript saves

    # Atelier (Creator OS) — all folders in rahm@rmasters.group Drive
    atelier_drive_account: str = "rahm@rmasters.group"
    atelier_root_folder_id: str = "1AxL5st3pmVNolAdSOVep1L-AgviPn7mB"           # rmg_creator_os
    atelier_content_engine_folder_id: str = "1k1WKwQKPawwUzUsdTWocay4R3_A04X44" # 06_CONTENT_ENGINE
    atelier_brand_assets_folder_id: str = "1gVfCOsoWCppdB5n62x2vCoAA845TT4KD"   # BRAND_ASSETS
    atelier_brand_assets_image_id: str = "1mbyi8HLcRlw8geBfHQ0eWZLIDmN5Qphu"   # BRAND_ASSETS/IMAGE
    atelier_brand_assets_audio_id: str = "1dLOGvgp2WzikRej4Km_Ntp6GQeQBC0as"   # BRAND_ASSETS/AUDIO
    atelier_brand_assets_video_id: str = "1DTc37GMeWJfgcN6yM-ftYp_abTlYb4g4"   # BRAND_ASSETS/VIDEO

    # Operational data sources for ALLIE (project mgmt + knowledge base)
    clickup_api_token: str = ""
    clickup_team_id: str = ""
    notion_api_key: str = ""
    # AMG (Cappo's domain) is its own system; flip on when Cappo matures under ALLIE.
    allie_amg_enabled: bool = False

    # Cappo — the AMG operations AI, reachable by ALLIE's delegate_to_cappo (keyed M2M call).
    cappo_agent_url: str = "https://cappo.apex-meridian-group.com/api/agent"
    cappo_agent_key: str = ""

    # Google — unified OAuth for Calendar + Gmail + Drive across all accounts.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    # Default account used when no account is specified in a tool call.
    default_google_account: str = "rahmind.consulting@rmoorind.com"
    # Legacy single-account calendar token (still honored for the default account).
    google_calendar_refresh_token: str = ""
    google_calendar_id: str = "primary"
    # Redirect URI for the legacy /oauth/calendar flow (kept for backward compat).
    google_oauth_redirect: str = "https://allen.i.verse.rmasters.group/oauth/calendar/callback"
    # Redirect URI for the new unified /oauth/google flow.
    google_oauth_unified_redirect: str = "https://allen.i.verse.rmasters.group/oauth/google/callback"

    # Twilio / WhatsApp bridge
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""  # e.g. whatsapp:+14155238886 (sandbox sender)
    twilio_whatsapp_to: str = ""    # e.g. whatsapp:+1YOURNUMBER (Rahm's personal number)
    daily_report_time: str = "07:00"  # HH:MM server local time (set TZ env var for offset)

    port: int = 8090

    @property
    def whatsapp_ready(self) -> bool:
        return bool(
            self.twilio_account_sid
            and self.twilio_auth_token
            and self.twilio_whatsapp_from
            and self.twilio_whatsapp_to
        )

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

    @property
    def youtube_ready(self) -> bool:
        return self.docs_ready and bool(self.gdrive_youtube_folder_id)


settings = Settings()
