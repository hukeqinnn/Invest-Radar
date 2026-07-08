from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .fetcher import USER_AGENT
from .files import date_prefix, slugify


def _extension_from_url(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".aac", ".m4a", ".mp3", ".ogg", ".wav", ".flac"}:
        return suffix
    return ".m4a"


def audio_path_for_item(audio_dir: Path, source_name: str, title: str, published_at: str, url: str) -> Path:
    source_dir = audio_dir / slugify(source_name, "source")
    source_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{date_prefix(published_at)}-{slugify(title)}{_extension_from_url(url)}"
    return source_dir / filename


def transcript_path_for_item(transcripts_dir: Path, source_name: str, title: str, published_at: str) -> Path:
    source_dir = transcripts_dir / slugify(source_name, "source")
    source_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{date_prefix(published_at)}-{slugify(title)}.full.md"
    return source_dir / filename


def download_audio(url: str, path: Path, timeout: int = 60) -> Path:
    if path.exists() and path.stat().st_size > 0:
        return path
    tmp_path = path.with_suffix(path.suffix + ".part")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "audio/*,*/*"})
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urlopen(request, timeout=timeout) as response, tmp_path.open("wb") as fh:
                shutil.copyfileobj(response, fh)
            break
        except Exception as exc:  # noqa: BLE001 - retry transient CDN resets/timeouts.
            last_error = exc
            if tmp_path.exists():
                tmp_path.unlink()
            if attempt == 3:
                raise
            time.sleep(attempt * 2)
    if last_error is not None and not tmp_path.exists():
        raise last_error
    tmp_path.replace(path)
    return path


def convert_to_wav(ffmpeg_command: str, audio_path: Path) -> Path:
    wav_path = audio_path.with_suffix(".whisper.wav")
    if wav_path.exists() and wav_path.stat().st_size > 0:
        return wav_path
    subprocess.run(
        [
            ffmpeg_command,
            "-y",
            "-i",
            str(audio_path),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(wav_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    return wav_path


def delete_audio_artifacts(audio_path: Path) -> None:
    for path in (audio_path, audio_path.with_suffix(".whisper.wav")):
        try:
            if path.exists() and path.is_file():
                path.unlink()
        except OSError:
            pass


def transcribe_audio(
    *,
    whisper_command: str,
    ffmpeg_command: str,
    model_path: Path,
    language: str,
    audio_path: Path,
    transcript_path: Path,
) -> str:
    if not model_path.exists():
        raise FileNotFoundError(f"Whisper model not found: {model_path}")

    wav_path = convert_to_wav(ffmpeg_command, audio_path)
    output_base = transcript_path.with_suffix("")
    txt_path = Path(str(output_base) + ".txt")
    if txt_path.exists() and txt_path.stat().st_size > 0:
        return txt_path.read_text(encoding="utf-8", errors="replace").strip()

    subprocess.run(
        [
            whisper_command,
            "-m",
            str(model_path),
            "-f",
            str(wav_path),
            "-l",
            language,
            "-otxt",
            "-of",
            str(output_base),
            "-np",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if not txt_path.exists():
        raise RuntimeError(f"Whisper did not write transcript: {txt_path}")
    transcript = txt_path.read_text(encoding="utf-8", errors="replace").strip()
    return transcript


def write_transcript_markdown(
    transcript_path: Path,
    *,
    title: str,
    source_name: str,
    published_at: str,
    link: str,
    audio_path: Path,
    transcript: str,
) -> Path:
    lines = [
        f"# {title}",
        "",
        f"- 来源: {source_name}",
        f"- 发布时间: {published_at or '未知'}",
        f"- 原始链接: {link or '无'}",
        f"- 本地音频: {audio_path}",
        "",
        "## 逐字稿",
        "",
        transcript,
    ]
    transcript_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return transcript_path
