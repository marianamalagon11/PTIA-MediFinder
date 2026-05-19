"""
Construye la knowledge base del LLM en ChromaDB.

Para cada principio activo genera un documento con:
  - Nombre en inglés (de principios_activos.csv, columna 'Nombre en Inglés')
  - Clasificación ATC / clase terapéutica (de medicamentos_invima.csv, columna 'descripcionatc')
  - Formas farmacéuticas disponibles en Colombia (de medicamentos_invima.csv)
  - Resumen de Wikipedia ES → EN como fallback

Ejecutar: python scripts/build_knowledge_base.py
"""

import re
import sys
import time
import unicodedata
from pathlib import Path

import chromadb
import pandas as pd
import wikipediaapi
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.config import settings


_EMBED_MODEL     = "paraphrase-multilingual-MiniLM-L12-v2"
_COLLECTION_NAME = "compuestos_kb"
_DELAY_WIKI      = 0.6  # segundos entre llamadas a Wikipedia

_wiki_es = wikipediaapi.Wikipedia(
    language="es",
    user_agent="MediFinder/1.0 (proyecto académico Colombia)"
)
_wiki_en = wikipediaapi.Wikipedia(
    language="en",
    user_agent="MediFinder/1.0 (proyecto académico Colombia)"
)


def _normalizar(texto) -> str:
    texto = str(texto) if texto and str(texto) != "nan" else ""
    nfkd  = unicodedata.normalize("NFKD", texto)
    sin_t = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_t.strip())


def cargar_principios() -> pd.DataFrame:
    """
    Carga principios_activos.csv.
    Columnas esperadas: 'Principio Activo', 'Nombre en Inglés', 'Cantidad de Medicamentos'
    """
    csv_path = Path(settings.csv_principios)
    if not csv_path.exists():
        print(f"[KB] principios_activos.csv no encontrado en {csv_path}")
        return pd.DataFrame()

    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    print(f"[KB] principios_activos.csv: {len(df)} filas, columnas: {list(df.columns)}")

    df.columns = [c.strip() for c in df.columns]
    return df


def cargar_atc_invima() -> dict[str, str]:
    """
    Extrae el mapeo principio_activo → descripcionatc desde medicamentos_invima.csv.
    Retorna dict: pa_normalizado → descripción ATC.
    """
    csv_invima = Path(settings.csv_invima)
    if not csv_invima.exists():
        print(f"[KB] medicamentos_invima.csv no encontrado en {csv_invima} → se omite ATC.")
        return {}

    df = pd.read_csv(csv_invima, encoding="utf-8-sig", low_memory=False,
                     usecols=["principioactivo", "descripcionatc"])
    df = df.dropna(subset=["principioactivo"])
    df["principioactivo"] = df["principioactivo"].apply(_normalizar).str.lower()
    df["descripcionatc"]  = df["descripcionatc"].apply(_normalizar)

    mapeo = (
        df.groupby("principioactivo")["descripcionatc"]
        .agg(lambda x: x.mode().iloc[0] if not x.mode().empty else "")
        .to_dict()
    )
    print(f"[KB] ATC cargado: {len(mapeo)} principios activos con clase terapéutica.")
    return mapeo


def cargar_formas_invima() -> dict[str, list[str]]:
    """
    Extrae las formas farmacéuticas disponibles por principio activo desde invima.
    Retorna dict: pa_normalizado → lista de formas únicas.
    """
    csv_invima = Path(settings.csv_invima)
    if not csv_invima.exists():
        return {}

    df = pd.read_csv(csv_invima, encoding="utf-8-sig", low_memory=False,
                     usecols=["principioactivo", "formafarmaceutica"])
    df = df.dropna(subset=["principioactivo", "formafarmaceutica"])
    df["principioactivo"]  = df["principioactivo"].apply(_normalizar).str.lower()
    df["formafarmaceutica"] = df["formafarmaceutica"].apply(_normalizar)

    mapeo = (
        df.groupby("principioactivo")["formafarmaceutica"]
        .apply(lambda x: list(x.dropna().unique()))
        .to_dict()
    )
    return mapeo



def _wiki_resumen(termino: str, termino_en: str = "") -> str:
    """Busca resumen en Wikipedia ES, fallback EN (usando nombre en inglés si está disponible)."""
    for wiki, busqueda in [(_wiki_es, termino), (_wiki_en, termino_en or termino)]:
        try:
            pagina = wiki.page(busqueda)
            if pagina.exists() and pagina.summary:
                idioma = "ES" if wiki == _wiki_es else "EN"
                return f"[Wikipedia {idioma}] {pagina.summary[:1500]}"
        except Exception:
            continue
        time.sleep(_DELAY_WIKI)
    return ""



def construir_documento(
    pa: str,
    nombre_en: str,
    clase_atc: str,
    formas: list[str],
) -> str:
    """
    Genera el texto del documento para el RAG.
    Combina datos de CSV + Wikipedia.
    """
    partes = [f"Principio activo: {pa}"]

    if nombre_en:
        partes.append(f"Nombre en inglés: {nombre_en}")

    if clase_atc:
        partes.append(f"Clasificación terapéutica (ATC): {clase_atc}")

    if formas:
        partes.append(f"Formas farmacéuticas disponibles en Colombia: {', '.join(formas[:6])}")

    resumen_wiki = _wiki_resumen(pa, nombre_en)
    if resumen_wiki:
        partes.append(resumen_wiki)
    else:
        partes.append(
            f"Nota: no se encontró información en Wikipedia para '{pa}'. "
            f"El modelo de lenguaje usará su conocimiento general."
        )

    return "\n".join(partes)



def main():
    df_pa       = cargar_principios()
    mapeo_atc   = cargar_atc_invima()
    mapeo_formas = cargar_formas_invima()

    if df_pa.empty:
        print("[KB] Extrayendo principios activos desde medicamentos_invima.csv...")
        csv_invima = Path(settings.csv_invima)
        if not csv_invima.exists():
            print("[ERROR] No hay fuente de principios activos. Abortando.")
            sys.exit(1)
        df_inv = pd.read_csv(csv_invima, encoding="utf-8-sig", low_memory=False,
                             usecols=["principioactivo"])
        pas_unicos = df_inv["principioactivo"].dropna().apply(_normalizar).unique()
        df_pa = pd.DataFrame({"Principio Activo": pas_unicos, "Nombre en Inglés": ""})
        print(f"[KB] {len(df_pa)} principios activos extraídos.")

    col_pa = next((c for c in df_pa.columns if "principio" in c.lower() or "activo" in c.lower()), None)
    col_en = next((c for c in df_pa.columns if "ingl" in c.lower() or "english" in c.lower()), None)

    if not col_pa:
        print(f"[ERROR] No se encontró columna de principio activo en el CSV.")
        print(f"  Columnas disponibles: {list(df_pa.columns)}")
        sys.exit(1)

    # ChromaDB
    db_path = Path(settings.embeddings_dir)
    db_path.mkdir(parents=True, exist_ok=True)
    client     = chromadb.PersistentClient(path=str(db_path))
    collection = client.get_or_create_collection(
        name=_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    ids_existentes = set(collection.get()["ids"])
    print(f"[KB] {len(ids_existentes)} documentos ya indexados en '{_COLLECTION_NAME}'.")

    print("[KB] Cargando modelo de embeddings de texto...")
    embedder = SentenceTransformer(_EMBED_MODEL)
    print("[KB] Listo. Iniciando indexación...\n")

    nuevos  = 0
    errores = 0

    for _, fila in tqdm(df_pa.iterrows(), total=len(df_pa), desc="Indexando PA"):
        pa       = _normalizar(fila[col_pa])
        pa_lower = pa.lower()
        nombre_en = _normalizar(fila[col_en]) if col_en else ""

        if not pa:
            continue

        doc_id = f"pa_{re.sub(r'[^a-z0-9]', '_', pa_lower)[:80]}"
        if doc_id in ids_existentes:
            continue

        try:
            clase_atc = mapeo_atc.get(pa_lower, "")
            formas    = mapeo_formas.get(pa_lower, [])

            doc = construir_documento(pa, nombre_en, clase_atc, formas)
            embedding = embedder.encode(doc, normalize_embeddings=True).tolist()

            collection.add(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[doc],
                metadatas=[{
                    "principio_activo": pa,
                    "nombre_en":        nombre_en,
                    "clase_atc":        clase_atc,
                }],
            )
            nuevos += 1

        except Exception as e:
            print(f"\n  [ERROR] {pa}: {e}")
            errores += 1

    print(f"\nKnowledge base construida.")
    print(f"   Documentos nuevos: {nuevos}")
    print(f"   Errores:           {errores}")
    print(f"   Total en KB:       {collection.count()}")
    print(f"   Guardada en:       {db_path}")


if __name__ == "__main__":
    main()