"""Markdown chunking that preserves heading context and line numbers for citations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


@dataclass
class Chunk:
    text: str
    heading: str  # nearest preceding heading path, e.g. "Kiến trúc > Qdrant"
    start_line: int  # 1-based, inclusive
    end_line: int  # 1-based, inclusive


@dataclass
class _Builder:
    lines: list[tuple[int, str]] = field(default_factory=list)

    def size(self) -> int:
        return sum(len(text) + 1 for _, text in self.lines)

    def is_blank(self) -> bool:
        return all(not text.strip() for _, text in self.lines)


def _heading_path(stack: list[tuple[int, str]]) -> str:
    return " > ".join(title for _, title in stack)


def _flush(builder: _Builder, heading: str, chunks: list[Chunk]) -> None:
    if not builder.lines or builder.is_blank():
        builder.lines.clear()
        return
    chunks.append(
        Chunk(
            text="\n".join(text for _, text in builder.lines).strip("\n"),
            heading=heading,
            start_line=builder.lines[0][0],
            end_line=builder.lines[-1][0],
        )
    )
    builder.lines.clear()


def _overlap_lines(lines: list[tuple[int, str]], overlap_chars: int) -> list[tuple[int, str]]:
    """Trailing lines of the previous chunk, up to overlap_chars, to seed the next chunk."""
    if overlap_chars <= 0:
        return []
    kept: list[tuple[int, str]] = []
    used = 0
    for number, text in reversed(lines):
        cost = len(text) + 1
        if kept and used + cost > overlap_chars:
            break
        kept.append((number, text))
        used += cost
        if used >= overlap_chars:
            break
    return list(reversed(kept))


def split_markdown(text: str, chunk_size: int = 1000, chunk_overlap: int = 100) -> list[Chunk]:
    """Split Markdown into chunks bounded by chunk_size characters.

    Chunks break preferentially at headings; each chunk records the heading path
    it belongs to and its 1-based line range in the source file.
    """
    chunks: list[Chunk] = []
    builder = _Builder()
    heading_stack: list[tuple[int, str]] = []
    current_heading = ""

    for number, line in enumerate(text.splitlines(), start=1):
        match = HEADING_RE.match(line)
        if match:
            _flush(builder, current_heading, chunks)
            level = len(match.group(1))
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, match.group(2)))
            current_heading = _heading_path(heading_stack)
            builder.lines.append((number, line))
            continue

        if builder.lines and builder.size() + len(line) + 1 > chunk_size:
            previous_lines = list(builder.lines)
            _flush(builder, current_heading, chunks)
            builder.lines.extend(_overlap_lines(previous_lines, chunk_overlap))
        builder.lines.append((number, line))

        # A single line longer than chunk_size still becomes its own chunk.
        if builder.size() > chunk_size and len(builder.lines) == 1:
            _flush(builder, current_heading, chunks)

    _flush(builder, current_heading, chunks)
    return chunks
