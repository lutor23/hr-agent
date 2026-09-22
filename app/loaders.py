"""Load the policy corpus (Markdown, HTML, PDF) into heading-aware chunks."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pymupdf
from bs4 import BeautifulSoup

MAX_CHARS = 1200

DOC_ID_RE = re.compile(r"Document ID:?\**\s*:?\s*([A-Z]+-[A-Z]+-\d+)")


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    source_file: str
    fmt: str
    text: str

    @property
    def embed_text(self) -> str:
        """Text that gets embedded: heading context improves short-chunk recall."""
        return f"{self.title} - {self.section}\n{self.text}"

    def metadata(self) -> dict:
        d = asdict(self)
        d.pop("text")
        return d


def split_text(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Greedily pack blank-line separated paragraphs up to max_chars.

    A paragraph (or table) longer than max_chars is split on line boundaries.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    for p in paragraphs:
        if len(p) <= max_chars:
            pieces.append(p)
            continue
        buf = ""
        for line in p.split("\n"):
            if buf and len(buf) + len(line) + 1 > max_chars:
                pieces.append(buf)
                buf = line
            else:
                buf = f"{buf}\n{line}" if buf else line
        if buf:
            pieces.append(buf)

    chunks: list[str] = []
    cur = ""
    for piece in pieces:
        if cur and len(cur) + len(piece) + 2 > max_chars:
            chunks.append(cur)
            cur = piece
        else:
            cur = f"{cur}\n\n{piece}" if cur else piece
    if cur:
        chunks.append(cur)
    return chunks


def _build_chunks(
    sections: list[tuple[str, str]], doc_id: str, title: str, path: Path, fmt: str
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section, body in sections:
        for i, piece in enumerate(split_text(body)):
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}-{len(chunks):03d}",
                    doc_id=doc_id,
                    title=title,
                    section=section,
                    source_file=path.name,
                    fmt=fmt,
                    text=piece,
                )
            )
    return chunks


def _clean_heading(h: str) -> str:
    return re.sub(r"^\d+(\.\d+)*\.?\s+", "", h).strip()


def load_markdown(path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    m = DOC_ID_RE.search(raw)
    doc_id = m.group(1) if m else path.stem
    title = next(
        (ln[2:].strip() for ln in raw.splitlines() if ln.startswith("# ")), path.stem
    )

    # sections[0] collects the preamble (Document ID / dates / owner), which is
    # metadata rather than policy content, and is dropped below.
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in raw.splitlines():
        if line.startswith("# ") or line.strip() == "---":
            continue
        if line.startswith("## "):
            sections.append((_clean_heading(line[3:]), []))
        else:
            sections[-1][1].append(line)

    return _build_chunks(
        [(name, "\n".join(lines)) for name, lines in sections[1:] if "".join(lines).strip()],
        doc_id, title, path, "markdown",
    )


def _html_table_to_text(table) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def load_html(path: Path) -> list[Chunk]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
    body = soup.body or soup
    m = DOC_ID_RE.search(body.get_text(" "))
    doc_id = m.group(1) if m else path.stem
    h1 = body.find("h1")
    title = h1.get_text(strip=True) if h1 else path.stem

    sections: list[tuple[str, list[str]]] = []
    for el in body.find_all(["h2", "h3", "p", "ul", "ol", "table"], recursive=False):
        if el.name == "h2":
            sections.append((_clean_heading(el.get_text(strip=True)), []))
        elif not sections:
            continue  # preamble metadata paragraphs before the first h2
        elif el.name == "h3":
            sections[-1][1].append(el.get_text(strip=True))
        elif el.name in ("ul", "ol"):
            sections[-1][1].append(
                "\n".join(f"- {li.get_text(' ', strip=True)}" for li in el.find_all("li"))
            )
        elif el.name == "table":
            sections[-1][1].append(_html_table_to_text(el))
        else:
            sections[-1][1].append(el.get_text(" ", strip=True))
    return _build_chunks(
        [(n, "\n\n".join(parts)) for n, parts in sections if parts],
        doc_id, title, path, "html",
    )


def load_pdf(path: Path) -> list[Chunk]:
    """Headings are detected by font size (title 18pt, section headings 13pt)."""
    lines: list[tuple[float, str]] = []
    with pymupdf.open(path) as doc:
        for page in doc:
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    text = "".join(s["text"] for s in line["spans"]).strip()
                    if text:
                        lines.append((max(s["size"] for s in line["spans"]), text))

    full = "\n".join(t for _, t in lines)
    m = DOC_ID_RE.search(full)
    doc_id = m.group(1) if m else path.stem
    title = next((t for size, t in lines if size >= 16), path.stem)

    sections: list[tuple[str, list[str]]] = []
    for size, text in lines:
        if size >= 16:
            continue
        if size >= 12.5:
            sections.append((_clean_heading(text), []))
        elif sections:
            sections[-1][1].append(text)
    # PDF text has no blank lines between paragraphs; join with single newlines and
    # let split_text break at line boundaries.
    return _build_chunks(
        [(n, "\n".join(parts)) for n, parts in sections if parts],
        doc_id, title, path, "pdf",
    )


def load_corpus(corpus_dir: str | Path) -> list[Chunk]:
    corpus_dir = Path(corpus_dir)
    chunks: list[Chunk] = []
    for path in sorted(corpus_dir.glob("markdown/*.md")):
        chunks += load_markdown(path)
    for path in sorted(corpus_dir.glob("html/*.html")):
        chunks += load_html(path)
    for path in sorted(corpus_dir.glob("pdf/*.pdf")):
        chunks += load_pdf(path)
    return chunks
