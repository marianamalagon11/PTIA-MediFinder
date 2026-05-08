import re
import unicodedata
from pathlib import Path

import anthropic
import chromadb
from sentence_transformers import SentenceTransformer

from app.config import settings



_embedder: SentenceTransformer | None = None
_kb_collection = None
_claude: anthropic.Anthropic | None = None

_COLLECTION_NAME = "compuestos_kb"
_EMBED_MODEL     = "paraphrase-multilingual-MiniLM-L12-v2" 


def _inicializar():
    global _embedder, _kb_collection, _claude

    if _embedder is None:
        print("[LLM] Cargando modelo de embeddings de texto...")
        _embedder = SentenceTransformer(_EMBED_MODEL)

    if _kb_collection is None:
        db_path = Path(settings.embeddings_dir)
        db_path.mkdir(parents=True, exist_ok=True)
        client       = chromadb.PersistentClient(path=str(db_path))
        _kb_collection = client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        print(f"[LLM] Knowledge base cargada. {_kb_collection.count()} documentos.")

    if _claude is None:
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY no está configurado en .env")
        _claude = anthropic.Anthropic(api_key=settings.anthropic_api_key)



def _recuperar_contexto(principio_activo: str, n_chunks: int = 4) -> str:
    """Busca los chunks más relevantes sobre el principio activo en ChromaDB."""
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



_SYSTEM_PROMPT = """Eres un asistente farmacéutico educativo para el sistema MediFinder, 
orientado a pacientes colombianos. Tu rol es explicar de manera clara, precisa y en español 
la información sobre principios activos de medicamentos.

Siempre incluye estas secciones en tu respuesta:
1. ¿Qué es? (descripción del compuesto y para qué sirve)
2. Composición / mecanismo de acción (breve, en términos entendibles)
3. Efectos secundarios más comunes
4. Contraindicaciones importantes
5. Advertencias de interacciones (qué NO combinar)
6. Recomendaciones generales al paciente

Usa un tono claro y empático. NO des diagnósticos ni reemplaces la consulta médica. 
Termina siempre recordando que deben consultar a su médico o farmacéutico."""


def explicar_compuesto(principio_activo: str) -> dict:
    """
    Genera una explicación completa del principio activo usando RAG + Claude API.

    Retorna:
    {
        "principio_activo": str,
        "explicacion": str,
        "fuente_kb": bool,   # True si se encontró info en la knowledge base
    }
    """
    _inicializar()

    contexto  = _recuperar_contexto(principio_activo)
    fuente_kb = bool(contexto)

    if contexto:
        user_msg = (
            f"Basándote en la siguiente información de nuestra base de conocimiento, "
            f"explica el principio activo '{principio_activo}' para un paciente colombiano:\n\n"
            f"--- Información disponible ---\n{contexto}\n---\n\n"
            f"Sigue el formato de las secciones indicadas."
        )
    else:
        user_msg = (
            f"Explica el principio activo '{principio_activo}' para un paciente colombiano. "
            f"Sigue el formato de las secciones indicadas. "
            f"Nota: usa tu conocimiento general ya que no tenemos información específica en nuestra base."
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
        explicacion = f"Error al consultar el modelo de lenguaje: {e}"

    return {
        "principio_activo": principio_activo,
        "explicacion":      explicacion,
        "fuente_kb":        fuente_kb,
    }