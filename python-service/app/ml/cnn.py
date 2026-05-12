from pathlib import Path

import chromadb
from app.config import settings

try:
    import torch
    import torch.nn as nn
    from PIL import Image, UnidentifiedImageError
    from torchvision import models, transforms
    _TORCH_DISPONIBLE = True
except ImportError:
    _TORCH_DISPONIBLE = False
    print("[CNN] PyTorch no instalado — búsqueda visual desactivada (OCR y KNN siguen funcionando).")



_modelo = None
_preprocess = None
_collection = None
_device = "cuda" if (_TORCH_DISPONIBLE and torch.cuda.is_available()) else "cpu"


def _cargar_modelo():
    global _modelo, _preprocess
    if not _TORCH_DISPONIBLE:
        return
    if _modelo is not None:
        return
    weights     = models.EfficientNet_B0_Weights.IMAGENET1K_V1
    modelo      = models.efficientnet_b0(weights=weights)
    modelo.classifier = nn.Identity()
    modelo.eval()
    modelo.to(_device)
    _modelo     = modelo
    _preprocess = weights.transforms()
    print(f"[CNN] EfficientNet-B0 cargado en {_device}.")


def _cargar_coleccion():
    global _collection
    if _collection is not None:
        return
    db_path = Path(settings.embeddings_dir)
    if not db_path.exists():
        raise FileNotFoundError(
            f"Base de embeddings no encontrada en {db_path}. "
            "Ejecuta scripts/build_embeddings.py primero."
        )
    client      = chromadb.PersistentClient(path=str(db_path))
    _collection = client.get_collection("medicamentos_img")
    print(f"[CNN] ChromaDB cargado. {_collection.count()} imágenes indexadas.")


def extraer_embedding(imagen_path: str) -> list[float] | None:
    if not _TORCH_DISPONIBLE:
        return None
    _cargar_modelo()
    try:
        img    = Image.open(imagen_path).convert("RGB")
        tensor = _preprocess(img).unsqueeze(0).to(_device)
        with torch.no_grad():
            emb = _modelo(tensor).squeeze().cpu().numpy()
        return emb.tolist()
    except Exception as e:
        print(f"[CNN] Error extrayendo embedding: {e}")
        return None


def buscar_similares_visual(imagen_path: str, n_resultados: int = 5) -> list[dict]:
    if not _TORCH_DISPONIBLE:
        return []
    _cargar_modelo()
    _cargar_coleccion()

    if _collection.count() == 0:
        print("[CNN] La base de embeddings está vacía. Ejecuta build_embeddings.py.")
        return []

    emb = extraer_embedding(imagen_path)
    if emb is None:
        return []

    try:
        resultados = _collection.query(
            query_embeddings=[emb],
            n_results=min(n_resultados, _collection.count()),
            include=["metadatas", "distances"],
        )
    except Exception as e:
        print(f"[CNN] Error en query ChromaDB: {e}")
        return []

    candidatos = []
    for meta, dist in zip(resultados["metadatas"][0], resultados["distances"][0]):
        similitud = round(1.0 - float(dist), 4)
        if similitud >= settings.cnn_similarity_threshold:
            candidatos.append({
                "nombre":           meta.get("nombre", ""),
                "principio_activo": meta.get("principio_activo", ""),
                "fuente":           meta.get("fuente", ""),
                "similitud":        similitud,
            })

    return candidatos