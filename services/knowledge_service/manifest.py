import hashlib
import json
import os

MANIFEST_FILENAME = ".manifest.json"


def compute_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def load_manifest(output_dir: str) -> dict:
    path = os.path.join(output_dir, MANIFEST_FILENAME)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_manifest(output_dir: str, manifest: dict) -> None:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, MANIFEST_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def is_unchanged(manifest: dict, source_name: str, content_hash: str) -> bool:
    entry = manifest.get(source_name)
    return entry is not None and entry.get("hash") == content_hash


def record_success(manifest: dict, source_name: str, content_hash: str, output_md: str, image_count: int) -> None:
    manifest[source_name] = {
        "hash": content_hash,
        "output_md": output_md,
        "image_count": image_count,
    }
