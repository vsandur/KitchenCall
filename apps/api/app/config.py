from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_menu_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "menu.json"


def _default_db_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "kitchencall.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KITCHENCALL_", env_file=".env", extra="ignore")

    menu_path: Path = _default_menu_path()
    database_path: Path = _default_db_path()
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # LiveKit access tokens for the dashboard (optional until you wire voice rooms)
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    # Worker availability heartbeat written by apps/agent
    agent_heartbeat_path: Path = Path("/tmp/kitchencall-agent-heartbeat.json")
    agent_heartbeat_stale_after_seconds: int = 20
    # Twilio bridge mode for inbound webhook response: say_only | stream | sip
    twilio_bridge_mode: str = "say_only"
    # When mode=stream, TwiML <Connect><Stream url="..."/>
    twilio_media_stream_url: str = ""
    # When mode=sip, TwiML <Dial><Sip>...</Sip></Dial>
    twilio_sip_uri: str = ""
    # Media Streams → STT → same process-turn as dashboard (Ticket 1 bridge)
    # off | faster_whisper | http (HTTP POST multipart wav to twilio_stt_http_url)
    twilio_stream_stt_backend: str = "off"
    twilio_stt_http_url: str = ""
    twilio_stt_http_timeout_seconds: float = 60.0
    twilio_whisper_model: str = "tiny"
    twilio_utterance_silence_ms: int = 700
    twilio_utterance_max_ms: int = 25_000
    twilio_utterance_rms_threshold: float = 280.0
    # Reserved for future <Start> streams; <Connect><Stream> always uses inbound_track per Twilio.
    twilio_stream_track: str = "inbound_track"
    # auto = enable outbound TTS when STT is on | off | on (force)
    twilio_stream_tts_backend: str = "auto"
    # Spoken before <Connect><Stream> (TwiML Say). Empty = use built-in ordering script.
    twilio_voice_greeting: str = ""
    # Transcript → actions: "rules" (default, zero cost) or "llm" / "openai" (synonym) for
    # OpenAI-compatible HTTP API — default URL is local Ollama (see docs/oss-stack.md).
    logic_extractor: str = "rules"
    llm_api_key: str = ""
    # Match a name from `ollama list` (e.g. llama3.2:3b); plain "llama3.2" fails if that tag is not pulled.
    llm_model: str = "llama3.2:3b"
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_timeout_seconds: float = 120.0


settings = Settings()
