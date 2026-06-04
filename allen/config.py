from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Auth — shared key required on /draft, /speak, /listen (blank = open).
    allen_api_key: str = ""

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

    port: int = 8090

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
