import json
import os
from pathlib import Path

import chromadb
import torch
import torch.nn as nn
from PIL import Image, UnidentifiedImageError
from torchvision import models, transforms
from tqdm import tqdm

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────

IMAGES_DIR     = Path("app/data/raw_images")
MANIFEST_PATH  = Path("app/data/scrape_manifest.json")
EMBEDDINGS_DIR = Path("app/data/embeddings_db")
BATCH_SIZE     = 16
DEVICE         = "cuda" if torch.cuda.is_available() else "cpu"

# ─── MODELO: EfficientNet-B0 pre-entrenado como extractor de embeddings ───────

def cargar_modelo() -> tuple[nn.Module, transforms.Compose]:
    weights = models.EfficientNet_B0_Weights.IMAGENET1K_V1
    modelo  = models.efficientnet_b0(weights=weights)

    # Reemplazar el clasificador final por identidad → salida = 1280-dim embedding
    modelo.classifier = nn.Identity()
    modelo.eval()
    modelo.to(DEVICE)

    preprocess = weights.transforms()  # preprocesamiento recomendado por torchvision
    return modelo, preprocess


# ─── EXTRACCIÓN DE EMBEDDING ──────────────────────────────────────────────────

def extraer_embedding(imagen_path: str, modelo: nn.Module, preprocess) -> list[float] | None:
    try:
        img = Image.open(imagen_path).convert("RGB")
        tensor = preprocess(img).unsqueeze(0).to(DEVICE)
        with torch.no_grad():
            embedding = modelo(tensor).squeeze().cpu().numpy()
        return embedding.tolist()
    except (UnidentifiedImageError, FileNotFoundError, Exception) as e:
        print(f"  [ERROR] {imagen_path}: {e}")
        return None


# ─── CONSTRUIR BASE DE EMBEDDINGS ─────────────────────────────────────────────

def construir_embeddings():
    print(f"[DEVICE] Usando: {DEVICE}")

    # Cargar modelo
    print("[MODELO] Cargando EfficientNet-B0...")
    modelo, preprocess = cargar_modelo()
    print("[MODELO] Listo.")

    # Conectar ChromaDB
    EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
    client     = chromadb.PersistentClient(path=str(EMBEDDINGS_DIR))
    collection = client.get_or_create_collection(
        name="medicamentos_img",
        metadata={"hnsw:space": "cosine"},  
    )

    # Obtener IDs ya indexados para no duplicar
    ids_existentes = set(collection.get()["ids"])
    print(f"[CHROMADB] {len(ids_existentes)} embeddings ya indexados.")

    # Cargar manifest del scraping
    if not MANIFEST_PATH.exists():
        print("[ERROR] No se encontró scrape_manifest.json. Ejecutá scrape_images.py primero.")
        return

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)

    # Filtrar imágenes nuevas (no indexadas aún)
    pendientes = [
        item for item in manifest
        if item.get("imagen_path") and
        Path(item["imagen_path"]).exists() and
        item["imagen_path"] not in ids_existentes
    ]

    print(f"[INFO] {len(pendientes)} imágenes nuevas para indexar.")
    if not pendientes:
        print("✅ Base de embeddings ya está al día.")
        return

    # Procesar en batches
    errores = 0
    for i in tqdm(range(0, len(pendientes), BATCH_SIZE), desc="Indexando"):
        batch = pendientes[i : i + BATCH_SIZE]

        ids        = []
        embeddings = []
        metadatas  = []

        for item in batch:
            emb = extraer_embedding(item["imagen_path"], modelo, preprocess)
            if emb is None:
                errores += 1
                continue

            ids.append(item["imagen_path"])
            embeddings.append(emb)
            metadatas.append({
                "nombre":          item.get("nombre", ""),
                "principio_activo": item.get("principio_activo", "sin_clasificar"),
                "fuente":          item.get("fuente", ""),
                "categoria":       item.get("categoria", ""),
            })

        if ids:
            collection.add(ids=ids, embeddings=embeddings, metadatas=metadatas)

    total = collection.count()
    print(f"\nIndexación completa.")
    print(f"   Embeddings en DB: {total}")
    print(f"   Errores:          {errores}")
    print(f"   DB guardada en:   {EMBEDDINGS_DIR}")


# ─── BÚSQUEDA POR SIMILITUD (función utilitaria para el CNN en runtime) ────────

def buscar_similares(
    imagen_path: str,
    n_resultados: int = 5,
) -> list[dict]:
    """
    Dado el path de una imagen nueva, retorna los N medicamentos más similares
    según similitud visual (coseno sobre embeddings EfficientNet).
    Esta función es la que el CNN llama en runtime como fallback del OCR.
    """
    modelo, preprocess = cargar_modelo()
    client     = chromadb.PersistentClient(path=str(EMBEDDINGS_DIR))
    collection = client.get_collection("medicamentos_img")

    emb = extraer_embedding(imagen_path, modelo, preprocess)
    if emb is None:
        return []

    resultados = collection.query(
        query_embeddings=[emb],
        n_results=n_resultados,
        include=["metadatas", "distances"],
    )

    candidatos = []
    for meta, dist in zip(resultados["metadatas"][0], resultados["distances"][0]):
        candidatos.append({
            "nombre":           meta["nombre"],
            "principio_activo": meta["principio_activo"],
            "fuente":           meta["fuente"],
            "similitud":        round(1 - dist, 4),  
        })

    return candidatos


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    construir_embeddings()

    # Demo: buscar similares para la primera imagen disponible
    print("\n─── Demo: búsqueda por similitud ───")
    imgs = list(IMAGES_DIR.rglob("*.jpg")) + list(IMAGES_DIR.rglob("*.png"))
    if imgs:
        print(f"Buscando similares a: {imgs[0]}")
        similares = buscar_similares(str(imgs[0]), n_resultados=3)
        for i, s in enumerate(similares, 1):
            print(f"  {i}. {s['nombre']} ({s['principio_activo']}) — similitud: {s['similitud']}")
    else:
        print("No hay imágenes para hacer demo. Ejecutá scrape_images.py primero.")