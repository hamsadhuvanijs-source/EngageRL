from urllib.parse import urlparse

import httpx
import trafilatura

USER_AGENT = "Mozilla/5.0 (compatible; StudyBot/1.0)"
REQUEST_TIMEOUT = 15.0


def extract_website(url: str) -> tuple[str, str]:
    """Fetch a page and pull clean, boilerplate-free article text out of it."""
    response = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT, follow_redirects=True)
    response.raise_for_status()

    text = trafilatura.extract(response.text, include_comments=False, include_tables=False)
    if not text or not text.strip():
        raise ValueError("Could not extract readable text from that page.")

    label = urlparse(url).netloc or url
    return text.strip(), label
