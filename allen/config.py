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
    atelier_root_folder_id: str = "1AxL5st3pmVNolAdSOVep1L-AgviPn7mB"             # rmg_creator_os
    atelier_content_engine_folder_id: str = "1k1WKwQKPawwUzUsdTWocay4R3_A04X44"   # 06_CONTENT_ENGINE
    # BRAND_ASSETS
    atelier_brand_assets_folder_id: str = "1gVfCOsoWCppdB5n62x2vCoAA845TT4KD"    # BRAND_ASSETS
    atelier_brand_assets_image_id: str = "1mbyi8HLcRlw8geBfHQ0eWZLIDmN5Qphu"     # BRAND_ASSETS/IMAGE
    atelier_brand_assets_audio_id: str = "1dLOGvgp2WzikRej4Km_Ntp6GQeQBC0as"     # BRAND_ASSETS/AUDIO
    atelier_brand_assets_video_id: str = "1DTc37GMeWJfgcN6yM-ftYp_abTlYb4g4"     # BRAND_ASSETS/VIDEO
    # VIDEO_PRODUCTION
    atelier_video_production_folder_id: str = "1VV_eiTLF51ZlAzakRd5E5VvLvJnS-QGp" # VIDEO_PRODUCTION
    atelier_aroll_folder_id: str = "1xNI7cx9-tjVvzzJbW5I40LvTd_vFXXpP"            # VIDEO_PRODUCTION/A_ROLL
    atelier_broll_folder_id: str = "1chUMHzHfWwTLu3DxOFG_lwMhLVJFJkFt"            # VIDEO_PRODUCTION/B_ROLL
    atelier_final_folder_id: str = "1pgNAh7UEtXd-tu1GeiySOA3m1u-jphWU"            # VIDEO_PRODUCTION/FINAL
    # THUMBNAIL_DESIGN
    atelier_thumbnail_folder_id: str = "13RjM4TBQANfj-2s_jfMI9vKwPpRgYTuN"       # THUMBNAIL_DESIGN
    atelier_thumbnail_approved_id: str = "1WNpoD8dFjEVN6qRAG-x0xGrnelTKWZSj"      # THUMBNAIL_DESIGN/APPROVED
    atelier_thumbnail_archived_id: str = "1GOLH9Kz_D_Q37rjQITfhs_-5curV9uFZ"      # THUMBNAIL_DESIGN/ARCHIVED

    # Operational data sources for ALLIE (project mgmt + knowledge base)
    clickup_api_token: str = ""
    clickup_team_id: str = ""
    notion_api_key: str = ""

    # GitHub App — ALLEN's own bot identity (allen-piaar-control-bot) across the
    # RMoor-Industries-Ltd-Co org. Issues read/write everywhere it's installed;
    # Contents write is restricted (at the tool layer) to rmg-piaar-system only.
    github_app_id: str = ""
    github_app_installation_id: str = ""
    github_app_private_key: str = ""  # PEM; \n-escaped when set as a single-line env var
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

    # Feed watch — ALLIE monitors social/momentum sources for "hot instrument"
    # signals and pushes them to Thoth (axis-tekhen). Off by default; needs a
    # ticker watchlist + Thoth endpoint/token to do anything.
    feed_watch_enabled: bool = False
    feed_watch_tickers: str = ""             # comma-separated, e.g. "AAPL,TSLA,NVDA"
    feed_watch_interval_minutes: int = 30
    thoth_ingest_url: str = ""               # e.g. https://axis-tekhen.rmasters.group/api/stocks/thoth/signals
    thoth_ingest_token: str = ""             # shared secret, must match axis-tekhen's THOTH_INGEST_TOKEN
    youtube_data_api_key: str = ""           # YouTube Data API v3 key — separate from yt-dlp ingest, needed for search

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
    def github_ready(self) -> bool:
        return bool(self.github_app_id and self.github_app_installation_id and self.github_app_private_key)

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

    @property
    def feed_watch_ready(self) -> bool:
        return bool(
            self.feed_watch_enabled
            and self.feed_watch_tickers.strip()
            and self.thoth_ingest_url
            and self.thoth_ingest_token
        )

    @property
    def youtube_search_ready(self) -> bool:
        return bool(self.youtube_data_api_key)


settings = Settings()
