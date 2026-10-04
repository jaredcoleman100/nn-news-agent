"""Document loader: a PDF/DOCX/TXT/MD path or URL becomes the primary context. Used for press releases,
board papers, concession decisions, public reports. Extracts text only; page count and source kept in meta."""
from __future__ import annotations
import re, tempfile
from pathlib import Path
from typing import Any
import httpx
from core.registry import register
from core.schema import Job, Context


def _pdf(path: Path) -> tuple[str, int]:
    import pdfplumber
    with pdfplumber.open(str(path)) as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages]
    return "\n\n".join(pages), len(pages)


def _docx(path: Path) -> tuple[str, int]:
    import docx
    d = docx.Document(str(path))
    return "\n".join(p.text for p in d.paragraphs), 0


def extract(path: Path) -> tuple[str, int]:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _pdf(path)
    if ext == ".docx":
        return _docx(path)
    return path.read_text(encoding="utf-8", errors="ignore"), 0


class DocumentLoader:
    name = "document"

    def load(self, job: Job, product: dict[str, Any]) -> Context:
        src = job.payload.get("path") or job.payload.get("url")
        if not src:
            raise ValueError("document loader needs payload.path or payload.url")
        if src.startswith("http"):
            r = httpx.get(src, timeout=60, follow_redirects=True); r.raise_for_status()
            suffix = Path(src.split("?")[0]).suffix or ".pdf"
            tmp = Path(tempfile.mkstemp(suffix=suffix)[1]); tmp.write_bytes(r.content); path = tmp
        else:
            path = Path(src)
        text, pages = extract(path)
        text = re.sub(r"[ \t]+", " ", text)
        max_chars = product.get("max_doc_chars", 120_000)
        truncated = len(text) > max_chars
        primary = {"title": job.payload.get("title") or path.name, "body": text[:max_chars], "url": src,
                   "published_at": job.payload.get("date")}
        return Context(primary=[primary], related=job.payload.get("related", []), beat=None,
                       meta={"pages": pages, "chars": len(text), "truncated": truncated, "document_kind": job.payload.get("kind"), "sender": job.payload.get("sender")})


register("loader", DocumentLoader())
