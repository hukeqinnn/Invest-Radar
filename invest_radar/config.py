from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "sources.toml"


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    type: str = "rss"
    enabled: bool = True
    fetch_full_pages: bool | None = None


@dataclass(frozen=True)
class Settings:
    database: Path
    reports_dir: Path
    texts_dir: Path
    audio_dir: Path
    transcripts_dir: Path
    max_items_per_source: int
    only_today: bool
    local_timezone: str
    fetch_full_pages: bool
    download_audio: bool
    transcribe_audio: bool
    delete_audio_after_transcription: bool
    max_transcriptions_per_run: int
    whisper_model: Path
    whisper_language: str
    whisper_command: str
    ffmpeg_command: str
    summary_mode: str
    max_llm_summaries_per_run: int
    summaries_dir: Path
    llm_base_url: str
    llm_model: str
    llm_api_key_env: str
    llm_keychain_service: str
    llm_keychain_account: str
    llm_reasoning_effort: str
    llm_verbosity: str
    llm_timeout_seconds: int
    llm_max_chars_per_chunk: int
    summary_sentences: int
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class AppConfig:
    path: Path
    root: Path
    settings: Settings
    sources: tuple[Source, ...]


def _resolve_path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return root / path


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path).expanduser().resolve() if path else DEFAULT_CONFIG
    root = config_path.parents[1] if config_path.parent.name == "config" else PROJECT_ROOT

    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)

    raw_settings = raw.get("settings", {})
    settings = Settings(
        database=_resolve_path(root, raw_settings.get("database", "data/radar.db")),
        reports_dir=_resolve_path(root, raw_settings.get("reports_dir", "reports")),
        texts_dir=_resolve_path(root, raw_settings.get("texts_dir", "data/texts")),
        audio_dir=_resolve_path(root, raw_settings.get("audio_dir", "data/audio")),
        transcripts_dir=_resolve_path(root, raw_settings.get("transcripts_dir", "data/transcripts")),
        max_items_per_source=int(raw_settings.get("max_items_per_source", 5)),
        only_today=bool(raw_settings.get("only_today", False)),
        local_timezone=str(raw_settings.get("local_timezone", "")),
        fetch_full_pages=bool(raw_settings.get("fetch_full_pages", False)),
        download_audio=bool(raw_settings.get("download_audio", True)),
        transcribe_audio=bool(raw_settings.get("transcribe_audio", True)),
        delete_audio_after_transcription=bool(raw_settings.get("delete_audio_after_transcription", False)),
        max_transcriptions_per_run=int(raw_settings.get("max_transcriptions_per_run", 1)),
        whisper_model=_resolve_path(root, raw_settings.get("whisper_model", "models/ggml-small.bin")),
        whisper_language=str(raw_settings.get("whisper_language", "zh")),
        whisper_command=str(raw_settings.get("whisper_command", "whisper-cli")),
        ffmpeg_command=str(raw_settings.get("ffmpeg_command", "ffmpeg")),
        summary_mode=str(raw_settings.get("summary_mode", "local")),
        max_llm_summaries_per_run=int(raw_settings.get("max_llm_summaries_per_run", 2)),
        summaries_dir=_resolve_path(root, raw_settings.get("summaries_dir", "data/summaries")),
        llm_base_url=str(raw_settings.get("llm_base_url", "https://api.openai.com/v1")),
        llm_model=str(raw_settings.get("llm_model", "gpt-5.5")),
        llm_api_key_env=str(raw_settings.get("llm_api_key_env", "OPENAI_API_KEY")),
        llm_keychain_service=str(raw_settings.get("llm_keychain_service", "invest-radar-openai-api-key")),
        llm_keychain_account=str(raw_settings.get("llm_keychain_account", "openai")),
        llm_reasoning_effort=str(raw_settings.get("llm_reasoning_effort", "low")),
        llm_verbosity=str(raw_settings.get("llm_verbosity", "medium")),
        llm_timeout_seconds=int(raw_settings.get("llm_timeout_seconds", 180)),
        llm_max_chars_per_chunk=int(raw_settings.get("llm_max_chars_per_chunk", 12000)),
        summary_sentences=int(raw_settings.get("summary_sentences", 8)),
        keywords=tuple(raw_settings.get("keywords", [])),
    )

    sources: list[Source] = []
    for item in raw.get("sources", []):
        if not item.get("name") or not item.get("url"):
            raise ValueError("Each source must include name and url")
        sources.append(
            Source(
                name=str(item["name"]),
                url=str(item["url"]),
                type=str(item.get("type", "rss")),
                enabled=bool(item.get("enabled", True)),
                fetch_full_pages=item.get("fetch_full_pages"),
            )
        )

    return AppConfig(
        path=config_path,
        root=root,
        settings=settings,
        sources=tuple(sources),
    )
