import os
import glob
import logging
import tempfile

from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel
from langchain_text_splitters import MarkdownTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct
import openai

import excel_ingest
import manifest as manifest_store
import vision

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "project_docs")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
DOCS_GLOB = os.getenv("DOCS_GLOB", "/app/project_data/docs/**/*.md")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 1000))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", 100))
EXCEL_SOURCE_DIR = os.getenv("EXCEL_SOURCE_DIR", "/app/project_data/excel_sources")
EXCEL_OUTPUT_DIR = os.getenv("EXCEL_OUTPUT_DIR", "/app/project_data/docs/imported")

# --- Initialize Global Objects ---
try:
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    openai_client = openai.OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
    ollama_client = openai.OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
except Exception as e:
    logger.error(f"Failed to initialize models or clients on startup: {e}", exc_info=True)
    embeddings = None
    qdrant_client = None
    openai_client = None
    ollama_client = None

app = FastAPI(title="Knowledge Curator Service")

splitter = MarkdownTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)


class SearchQuery(BaseModel):
    query: str
    limit: int = 3


class AnswerQuery(BaseModel):
    question: str
    limit: int = 3
    use_online_model: int = 0  # 0 = Ollama (local), 1 = OpenAI gpt-4o-mini (online)


class IngestExcelRequest(BaseModel):
    use_online_model: int = 0  # 0 = Ollama (local), 1 = OpenAI gpt-4o-mini (online) cho bước refine
    force: bool = False


def _ensure_collection(vector_size: int):
    existing = [c.name for c in qdrant_client.get_collections().collections]
    if COLLECTION_NAME not in existing:
        qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )


@app.get("/")
def read_root():
    return {"message": "Knowledge Curator Service is running."}


@app.post("/ingest")
def ingest_documents():
    """
    Walks DOCS_GLOB, splits each Markdown file into chunks, embeds them,
    and upserts them into the Qdrant collection.
    """
    if not embeddings or not qdrant_client:
        raise HTTPException(status_code=503, detail="Embeddings model or Qdrant client is not available.")

    files = glob.glob(DOCS_GLOB, recursive=True)
    if not files:
        raise HTTPException(status_code=404, detail=f"No markdown files found matching '{DOCS_GLOB}'.")

    points = []
    point_id = 0
    for file_path in files:
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()

        for chunk in splitter.split_text(text):
            points.append((point_id, chunk, file_path))
            point_id += 1

    if not points:
        raise HTTPException(status_code=404, detail="No content found to ingest.")

    vectors = embeddings.embed_documents([p[1] for p in points])
    _ensure_collection(len(vectors[0]))

    qdrant_client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            PointStruct(id=pid, vector=vector, payload={"text": chunk, "source": source})
            for (pid, chunk, source), vector in zip(points, vectors)
        ],
    )

    return {"message": f"Ingested {len(points)} chunks from {len(files)} files.", "files": files}


@app.post("/search")
def search_documents(search_query: SearchQuery) -> list:
    if not embeddings or not qdrant_client:
        raise HTTPException(status_code=503, detail="Embeddings model or Qdrant client is not available.")

    query_vector = embeddings.embed_query(search_query.query)
    results = qdrant_client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_vector,
        limit=search_query.limit,
    )

    return [
        {"text": r.payload.get("text"), "source": r.payload.get("source"), "score": r.score}
        for r in results
    ]


@app.post("/answer")
def get_answer(answer_query: AnswerQuery):
    use_online = answer_query.use_online_model == 1

    if use_online:
        if not openai_client:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured.")
        client, model = openai_client, OPENAI_MODEL
    else:
        if not ollama_client:
            raise HTTPException(status_code=503, detail="Ollama client is not available.")
        client, model = ollama_client, OLLAMA_MODEL

    matches = search_documents(SearchQuery(query=answer_query.question, limit=answer_query.limit))
    if not matches:
        raise HTTPException(status_code=404, detail="No relevant documents found for this question.")

    context = "\n\n".join(f"[{m['source']}]\n{m['text']}" for m in matches)
    prompt = (
        "You are a project assistant. Answer the question using ONLY the context below. "
        "If the answer isn't in the context, say you don't know.\n\n"
        f"Context:\n{context}\n\nQuestion: {answer_query.question}"
    )

    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        logger.error(f"Chat completion failed (model={model}, online={use_online}): {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Failed to get response from model '{model}'.")

    return {
        "answer": completion.choices[0].message.content,
        "sources": [m["source"] for m in matches],
        "model_used": model,
    }


def _select_chat_client(use_online_model: int):
    if use_online_model == 1:
        if not openai_client:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured.")
        return openai_client, OPENAI_MODEL
    if not ollama_client:
        raise HTTPException(status_code=503, detail="Ollama client is not available.")
    return ollama_client, OLLAMA_MODEL


def _check_vision_available():
    if vision.VISION_PROVIDER == "anthropic" and not vision.anthropic_vision_client:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY is not configured (required for VISION_PROVIDER=anthropic).",
        )
    if vision.VISION_PROVIDER == "openai" and not vision.openai_vision_client:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured (required for VISION_PROVIDER=openai).",
        )


@app.post("/ingest-excel")
def ingest_excel(request: IngestExcelRequest):
    """
    Quét EXCEL_SOURCE_DIR, convert từng file .xlsx chưa xử lý (hoặc đã đổi nội dung) thành
    Markdown trong EXCEL_OUTPUT_DIR, dùng vision LLM để caption ảnh nhúng và text LLM để làm sạch
    format cuối cùng.
    """
    _check_vision_available()
    client, model = _select_chat_client(request.use_online_model)

    files = glob.glob(os.path.join(EXCEL_SOURCE_DIR, "*.xlsx"))
    if not files:
        raise HTTPException(status_code=404, detail=f"No .xlsx files found in '{EXCEL_SOURCE_DIR}'.")

    manifest = manifest_store.load_manifest(EXCEL_OUTPUT_DIR)
    processed, skipped, failed = [], [], []

    for path in files:
        name = os.path.basename(path)
        with open(path, "rb") as f:
            content = f.read()
        content_hash = manifest_store.compute_hash(content)

        if not request.force and manifest_store.is_unchanged(manifest, name, content_hash):
            skipped.append(name)
            continue

        try:
            result = excel_ingest.process_excel_file(path, EXCEL_OUTPUT_DIR, client, model)
            manifest_store.record_success(manifest, name, content_hash, result["output_md"], result["image_count"])
            manifest_store.save_manifest(EXCEL_OUTPUT_DIR, manifest)
            processed.append({"file": name, **result})
        except Exception as e:
            logger.error(f"Failed to process '{name}': {e}", exc_info=True)
            failed.append({"file": name, "error": str(e)})

    return {"processed": processed, "skipped": skipped, "failed": failed}


@app.post("/ingest-excel/upload")
async def ingest_excel_upload(use_online_model: int = 0, file: UploadFile = File(...)):
    """Upload 1 file .xlsx ad-hoc và xử lý ngay (không qua manifest skip)."""
    _check_vision_available()
    client, model = _select_chat_client(use_online_model)

    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = excel_ingest.process_excel_file(tmp_path, EXCEL_OUTPUT_DIR, client, model)
    except Exception as e:
        logger.error(f"Failed to process uploaded file '{file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process uploaded file: {e}")
    finally:
        os.remove(tmp_path)

    manifest = manifest_store.load_manifest(EXCEL_OUTPUT_DIR)
    content_hash = manifest_store.compute_hash(content)
    manifest_store.record_success(manifest, file.filename, content_hash, result["output_md"], result["image_count"])
    manifest_store.save_manifest(EXCEL_OUTPUT_DIR, manifest)

    return {"file": file.filename, **result}
