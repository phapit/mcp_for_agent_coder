"""Stable document identity and change detection for incremental ingestion."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


def content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def document_id(source: str, project_name: str | None = None) -> str:
    normalized = str(Path(source.replace("\\", "/")).as_posix()).lower()
    scope = f"{project_name.strip().lower()}:{normalized}" if project_name else normalized
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()


def chunk_id(doc_id: str, chunk_index: int, chunk_text: str) -> str:
    material = f"{doc_id}:{chunk_index}:{chunk_text}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def source_key(source: str) -> str:
    normalized = source.replace("\\", "/")
    return re.sub(r"/+", "/", str(Path(normalized).as_posix())).strip("/")
