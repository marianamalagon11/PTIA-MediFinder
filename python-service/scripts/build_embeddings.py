from pathlib import Path
import json

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

# Palabras que indican imágenes promocionales — se omiten del embedding
_NOMBRES_PROMO = [
    "primera compra", "domicilio", "aprovecha", "prime",
    "descuento", "oferta", "sin_nombre", "app y web",
]


# ─── MODELO ───────────────────────────────────────────────────────────────────

def cargar_modelo() -> tuple[nn.Module, transforms.Compose]:
    weights   = models.EfficientNet_B0_Weights.IMAGENET1K_V1
    modelo    = models.efficientnet_b0(weights=weights)
    modelo.classifier = nn.Identity()
    modelo.eval()
    modelo.to(DEVICE)
    return modelo, weights.transforms()


# ─── EMBEDDING ────────────────────────────────────────────────────────────────

def extraer_embedding(imagen_path: str, modelo: nn.Module, preprocess) -> list[float] | None:
    try:
        img    = Image.open(imagen_path).convert("RGB")
        tensor = preprocess(img).unsqueeze(0).to(DEVICE)
        with torch.no_grad():
            emb = modelo(tensor).squeeze().cpu().numpy()
        return emb.tolist()
    except (UnidentifiedImageError, FileNotFoundError, Exception) as e:
        print(f"  [ERROR] {imagen_path}: {e}")
        return None


def es_promo(nombre: str) -> bool:
    nombre_l = nombre.lower()
    return any(p in nombre_l for p in _NOMBRES_PROMO)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def construir_embeddings():
    print(f"[DEVICE] Usando: {DEVICE}")

    print("[MODELO] Cargando EfficientNet-B0...")
    modelo, preprocess = cargar_modelo()
    print("[MODELO] Listo.")

    EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
    client     = chromadb.PersistentClient(path=str(EMBEDDINGS_DIR))
    collection = client.get_or_create_collection(
        name="medicamentos_img",
        metadata={"hnsw:space": "cosine"},
    )

    ids_existentes = set(collection.get()["ids"])
    print(f"[CHROMADB] {len(ids_existentes)} embeddings ya indexados.")

    if not MANIFEST_PATH.exists():
        print("[ERROR] No se encontró scrape_manifest.json. Ejecutá scrape_images.py primero.")
        return

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)

    # ── Filtrar y deduplicar ANTES de procesar ────────────────────────────────
    vistos   = set()
    pendientes = []
    omitidos_promo   = 0
    omitidos_dup     = 0
    omitidos_nofile  = 0

    for item in manifest:
        path = item.get("imagen_path", "")
        nombre = item.get("nombre", "")

        if not path or not Path(path).exists():
            omitidos_nofile += 1
            continue

        if es_promo(nombre):
            omitidos_promo += 1
            continue

        if path in ids_existentes or path in vistos:
            omitidos_dup += 1
            continue

        vistos.add(path)
        pendientes.append(item)

    print(f"[INFO] {len(pendientes)} imágenes nuevas para indexar.")
    print(f"       Omitidas (promo):      {omitidos_promo}")
    print(f"       Omitidas (duplicadas): {omitidos_dup}")
    print(f"       Omitidas (sin archivo): {omitidos_nofile}")

    if not pendientes:
        print("✅ Base de embeddings ya está al día.")
        return

    # ── Procesar en batches ───────────────────────────────────────────────────
    errores = 0
    for i in tqdm(range(0, len(pendientes), BATCH_SIZE), desc="Indexando"):
        batch = pendientes[i : i + BATCH_SIZE]

        # Deduplicar dentro del batch por si acaso
        batch_ids_vistos = set()
        ids        = []
        embeddings = []
        metadatas  = []

        for item in batch:
            path = item["imagen_path"]
            if path in batch_ids_vistos:
                continue
            batch_ids_vistos.add(path)

            emb = extraer_embedding(path, modelo, preprocess)
            if emb is None:
                errores += 1
                continue

            ids.append(path)
            embeddings.append(emb)
            metadatas.append({
                "nombre":           item.get("nombre", ""),
                "principio_activo": item.get("principio_activo", "sin_clasificar"),
                "fuente":           item.get("fuente", ""),
                "categoria":        item.get("categoria", ""),
            })

        if ids:
            collection.add(ids=ids, embeddings=embeddings, metadatas=metadatas)

    total = collection.count()
    print(f"\n✅ Indexación completa.")
    print(f"   Embeddings en DB: {total}")
    print(f"   Errores:          {errores}")
    print(f"   DB guardada en:   {EMBEDDINGS_DIR}")


def buscar_similares(imagen_path: str, n_resultados: int = 5) -> list[dict]:
    modelo, preprocess = cargar_modelo()
    client     = chromadb.PersistentClient(path=str(EMBEDDINGS_DIR))
    collection = client.get_collection("medicamentos_img")

    emb = extraer_embedding(imagen_path, modelo, preprocess)
    if emb is None:
        return []

    resultados = collection.query(
        query_embeddings=[emb],
        n_results=min(n_resultados, collection.count()),
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


if __name__ == "__main__":
    construir_embeddings()

    print("\n─── Demo: búsqueda por similitud ───")
    imgs = list(IMAGES_DIR.rglob("*.jpg")) + list(IMAGES_DIR.rglob("*.png"))
    imgs_validas = [i for i in imgs if not es_promo(i.stem)]
    if imgs_validas:
        print(f"Buscando similares a: {imgs_validas[0]}")
        similares = buscar_similares(str(imgs_validas[0]), n_resultados=3)
        for i, s in enumerate(similares, 1):
            print(f"  {i}. {s['nombre']} ({s['principio_activo']}) — similitud: {s['similitud']}")
    else:
        print("No hay imágenes válidas para el demo.")