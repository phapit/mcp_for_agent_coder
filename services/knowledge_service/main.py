import os
import glob
import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langchain_text_splitters import MarkdownTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct
import openai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "project_docs")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DOCS_GLOB = os.getenv("DOCS_GLOB", "/app/project_data/docs/**/*.md")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 1000))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", 100))

# --- Initialize Global Objects ---
try:
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    openai_client = openai.OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except Exception as e:
    logger.error(f"Failed to initialize models or clients on startup: {e}", exc_info=True)
    embeddings = None
    qdrant_client = None
    openai_client = None

app = FastAPI(title="Knowledge Curator Service")

splitter = MarkdownTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)


class SearchQuery(BaseModel):
    query: str
    limit: int = 3


class AnswerQuery(BaseModel):
    question: str
    limit: int = 3


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
    if not openai_client:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured.")

    matches = search_documents(SearchQuery(query=answer_query.question, limit=answer_query.limit))
    if not matches:
        raise HTTPException(status_code=404, detail="No relevant documents found for this question.")

    context = "\n\n".join(f"[{m['source']}]\n{m['text']}" for m in matches)
    prompt = (
        "You are a project assistant. Answer the question using ONLY the context below. "
        "If the answer isn't in the context, say you don't know.\n\n"
        f"Context:\n{context}\n\nQuestion: {answer_query.question}"
    )

    completion = openai_client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
    )

    return {
        "answer": completion.choices[0].message.content,
        "sources": [m["source"] for m in matches],
    }
