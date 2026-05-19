import re
import unicodedata
from pathlib import Path

import anthropic
import chromadb
from sentence_transformers import SentenceTransformer

from app.config import settings


_embedder = None
_kb_collection = None
_claude = None

_COLLECTION_NAME = "compuestos_kb"
_EMBED_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


def _inicializar():
    global _embedder, _kb_collection, _claude

    if _embedder is None:
        print("[LLM] Cargando modelo de embeddings...")
        _embedder = SentenceTransformer(_EMBED_MODEL)

    if _kb_collection is None:
        db_path = Path(settings.embeddings_dir)
        db_path.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(db_path))
        _kb_collection = client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        print(f"[LLM] Knowledge base lista. {_kb_collection.count()} documentos.")

    if _claude is None:
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY no está configurado en .env")
        _claude = anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _recuperar_contexto(principio_activo, n_chunks=4):
    _inicializar()

    if _kb_collection.count() == 0:
        return ""

    query_emb = _embedder.encode(principio_activo, normalize_embeddings=True).tolist()
    resultados = _kb_collection.query(
        query_embeddings=[query_emb],
        n_results=min(n_chunks, _kb_collection.count()),
        include=["documents", "metadatas"],
    )

    chunks = resultados.get("documents", [[]])[0]
    return "\n\n".join(chunks) if chunks else ""


# prompt del sistema — le pedimos que use secciones simples y nada de markdown
_SYSTEM_PROMPT = """Eres un asistente farmacéutico educativo para pacientes colombianos.
Explica principios activos en español, de forma clara y breve.

Usa solo estos encabezados seguidos de dos puntos: "Qué es:", "Cómo actúa:", "Efectos secundarios:", "Contraindicaciones:", "Interacciones:", "Recomendaciones:".
Escribe en texto plano. No uses #, **, *, ---, emojis ni ningún símbolo de markdown.
Cada sección máximo 2 oraciones. Sin listas. Tono directo y útil."""


def explicar_compuesto(principio_activo):
    _inicializar()

    contexto = _recuperar_contexto(principio_activo)
    fuente_kb = bool(contexto)

    if contexto:
        user_msg = (
            f"Explica '{principio_activo}' usando esta información:\n\n"
            f"{contexto}\n\nUsa el formato de secciones. Texto plano."
        )
    else:
        user_msg = (
            f"Explica '{principio_activo}' para un paciente colombiano. "
            f"Usa el formato de secciones. Texto plano."
        )

    try:
        response = _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        explicacion = response.content[0].text
    except anthropic.APIError as e:
        explicacion = f"Error al consultar el modelo: {e}"

    return {
        "principio_activo": principio_activo,
        "explicacion": explicacion,
        "fuente_kb": fuente_kb,
    }
