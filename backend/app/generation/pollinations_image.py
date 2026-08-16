import hashlib
import random
import time
from pathlib import Path
from urllib.parse import quote

import httpx

# Pollinations.ai — free, keyless text-to-image over a plain HTTP GET. It rate-limits to
# effectively one in-flight request per client: firing requests in parallel got most of them an
# instant 429, so callers must generate sequentially, with a short retry-with-backoff on 429.
POLLINATIONS_URL_TEMPLATE = "https://image.pollinations.ai/prompt/{prompt}"
IMAGE_TIMEOUT_SECONDS = 60.0
MAX_RETRIES = 4
RETRY_BACKOFF_SECONDS = 3.0


def generate_image(prompt: str, dest: Path, size: int = 768, seed: int | None = None) -> None:
    """Downloads one image from Pollinations. Passing an explicit random seed (rather than
    relying on their default) avoids any response caching/dedup keyed on the request params."""
    url = POLLINATIONS_URL_TEMPLATE.format(prompt=quote(prompt))
    if seed is None:
        seed = random.randint(0, 2_147_483_647)

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = httpx.get(
                url,
                params={"width": size, "height": size, "nologo": "true", "seed": seed},
                timeout=IMAGE_TIMEOUT_SECONDS,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            last_exc = exc
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
            continue

        if response.status_code == 429:
            last_exc = RuntimeError("Rate limited by Pollinations")
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
            continue

        response.raise_for_status()
        dest.write_bytes(response.content)
        return

    raise last_exc or RuntimeError("Image generation failed after retries")


DEDUP_MAX_RETRIES = 2


def generate_unique_image(prompt: str, dest: Path, seen_hashes: set[str], size: int = 768) -> None:
    """Same as generate_image, but re-rolls the seed if the result is byte-identical to an
    earlier image in this batch. Pollinations occasionally serves a generic fallback image
    (observed identically across genuinely different prompts) instead of a real per-prompt
    generation — a fresh seed on retry is enough to get past it."""
    for attempt in range(DEDUP_MAX_RETRIES + 1):
        generate_image(prompt, dest, size=size)
        digest = hashlib.md5(dest.read_bytes()).hexdigest()
        if digest not in seen_hashes or attempt == DEDUP_MAX_RETRIES:
            seen_hashes.add(digest)
            return
