from __future__ import annotations

from dataclasses import dataclass
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 InvestRadar/0.1"
)


@dataclass(frozen=True)
class FetchResult:
    url: str
    body: str
    content_type: str


def fetch_text(url: str, timeout: int = 30, retries: int = 3) -> FetchResult:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml, text/html, */*",
        },
    )
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                content_type = response.headers.get("Content-Type", "")
            break
        except HTTPError as exc:
            last_error = exc
            if 400 <= exc.code < 500:
                raise RuntimeError(f"HTTP {exc.code} while fetching {url}") from exc
        except (URLError, ConnectionError, TimeoutError, OSError) as exc:
            last_error = exc

        if attempt < retries:
            time.sleep(min(2 ** (attempt - 1), 4))
    else:
        if isinstance(last_error, URLError):
            raise RuntimeError(f"Network error while fetching {url}: {last_error.reason}") from last_error
        raise RuntimeError(f"Network error while fetching {url}: {last_error}") from last_error

    encoding = "utf-8"
    if "charset=" in content_type:
        encoding = content_type.split("charset=", 1)[1].split(";", 1)[0].strip()
    return FetchResult(url=url, body=raw.decode(encoding, errors="replace"), content_type=content_type)
