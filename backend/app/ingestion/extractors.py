from pathlib import Path

from pypdf import PdfReader

SUPPORTED_EXTENSIONS = {".pdf": "pdf", ".txt": "txt"}


def file_type_for(filename: str) -> str | None:
    return SUPPORTED_EXTENSIONS.get(Path(filename).suffix.lower())


def extract_text(path: Path, file_type: str) -> str:
    if file_type == "pdf":
        return _extract_pdf(path)
    if file_type == "txt":
        return path.read_text(encoding="utf-8", errors="ignore")
    raise ValueError(f"Unsupported file_type: {file_type}")


def _extract_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages).strip()
