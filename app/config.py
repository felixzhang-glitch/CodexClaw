from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    feishu_app_id: str = Field(default="", validation_alias="FEISHU_APP_ID")
    feishu_app_secret: str = Field(default="", validation_alias="FEISHU_APP_SECRET")
    feishu_verification_token: str = Field(default="", validation_alias="FEISHU_VERIFICATION_TOKEN")
    feishu_encrypt_key: str = Field(default="", validation_alias="FEISHU_ENCRYPT_KEY")
    feishu_api_base: str = Field(default="https://open.feishu.cn", validation_alias="FEISHU_API_BASE")
    feishu_bot_open_id: str = Field(default="", validation_alias="FEISHU_BOT_OPEN_ID")
    feishu_group_require_mention: bool = Field(default=True, validation_alias="FEISHU_GROUP_REQUIRE_MENTION")
    feishu_max_retries: int = Field(default=2, validation_alias="FEISHU_MAX_RETRIES")
    feishu_retry_backoff_seconds: float = Field(default=0.5, validation_alias="FEISHU_RETRY_BACKOFF_SECONDS")

    codex_api_base: str = Field(default="https://api.openai.com/v1", validation_alias="CODEX_API_BASE")
    codex_api_key: str = Field(default="", validation_alias="CODEX_API_KEY")
    codex_model: str = Field(default="", validation_alias="CODEX_MODEL")
    codex_cli_bin: str = Field(
        default="/Applications/Codex.app/Contents/Resources/codex",
        validation_alias="CODEX_CLI_BIN",
    )
    codex_work_dir: str = Field(default="/Users/cesclaw/Desktop/All of CDOU", validation_alias="CODEX_WORK_DIR")
    codex_generated_images_dir: str = Field(
        default="~/.codex/generated_images",
        validation_alias="CODEX_GENERATED_IMAGES_DIR",
    )
    codex_permission_mode: str = Field(default="full", validation_alias="CODEX_PERMISSION_MODE")
    codex_timeout_seconds: float = Field(default=30.0, validation_alias="CODEX_TIMEOUT_SECONDS")
    codex_stream_read_limit_bytes: int = Field(default=262144, validation_alias="CODEX_STREAM_READ_LIMIT_BYTES")
    codex_max_retries: int = Field(default=2, validation_alias="CODEX_MAX_RETRIES")
    codex_retry_backoff_seconds: float = Field(default=1.0, validation_alias="CODEX_RETRY_BACKOFF_SECONDS")
    codex_circuit_breaker_threshold: int = Field(default=5, validation_alias="CODEX_CIRCUIT_BREAKER_THRESHOLD")
    codex_circuit_breaker_cooldown_seconds: int = Field(
        default=30,
        validation_alias="CODEX_CIRCUIT_BREAKER_COOLDOWN_SECONDS",
    )
    codex_allowed_user_ids: str = Field(default="", validation_alias="CODEX_ALLOWED_USER_IDS")
    codex_trigger_required: bool = Field(default=True, validation_alias="CODEX_TRIGGER_REQUIRED")
    codex_trigger_prefixes: str = Field(
        default="/codex,联动 Codex,联动codex,交给 Codex,让 Codex 处理",
        validation_alias="CODEX_TRIGGER_PREFIXES",
    )

    max_history_rounds: int = Field(default=10, validation_alias="MAX_HISTORY_ROUNDS")
    streaming_enabled: bool = Field(default=True, validation_alias="STREAMING_ENABLED")
    task_running_notice_seconds: float = Field(default=30.0, validation_alias="TASK_RUNNING_NOTICE_SECONDS")
    feishu_message_chunk_chars: int = Field(default=120, validation_alias="FEISHU_MESSAGE_CHUNK_CHARS")
    feishu_stream_flush_seconds: float = Field(default=1.0, validation_alias="FEISHU_STREAM_FLUSH_SECONDS")
    deduplicate_ttl_seconds: int = Field(default=3600, validation_alias="DEDUPLICATE_TTL_SECONDS")
    reminder_store_path: str = Field(default="./runtime/server/reminders.json", validation_alias="REMINDER_STORE_PATH")

    server_host: str = Field(default="0.0.0.0", validation_alias="SERVER_HOST")
    server_port: int = Field(default=8080, validation_alias="SERVER_PORT")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    @property
    def codex_chat_completions_url(self) -> str:
        return f"{self.codex_api_base.rstrip('/')}/chat/completions"

    @property
    def feishu_tenant_token_url(self) -> str:
        return f"{self.feishu_api_base.rstrip('/')}/open-apis/auth/v3/tenant_access_token/internal"

    @property
    def feishu_reply_url_template(self) -> str:
        base = self.feishu_api_base.rstrip("/")
        return f"{base}/open-apis/im/v1/messages/{{message_id}}/reply"

    @property
    def feishu_send_message_url(self) -> str:
        base = self.feishu_api_base.rstrip("/")
        return f"{base}/open-apis/im/v1/messages"

    @property
    def feishu_image_upload_url(self) -> str:
        base = self.feishu_api_base.rstrip("/")
        return f"{base}/open-apis/im/v1/images"

    @property
    def feishu_reaction_url_template(self) -> str:
        base = self.feishu_api_base.rstrip("/")
        return f"{base}/open-apis/im/v1/messages/{{message_id}}/reactions"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
