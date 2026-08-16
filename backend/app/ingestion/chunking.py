CHUNK_SIZE = 2000
CHUNK_OVERLAP = 200


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[dict]:
    text = text.strip()
    if not text:
        return []

    chunks = []
    start = 0
    index = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append({"index": index, "text": text[start:end]})
        index += 1
        if end == len(text):
            break
        start = end - overlap
    return chunks
