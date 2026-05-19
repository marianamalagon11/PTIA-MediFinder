import re
import unicodedata
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from rapidfuzz import fuzz, process as rfprocess

from app.config import settings

# nombres posibles de las columnas según el CSV del INVIMA
_CANDIDATOS = {
    "nombre": ["nombre_comercial", "producto", "descripcioncomercial"],
    "pa":     ["principio_activo", "principioactivo"],
    "conc":   ["concentracion"],
    "forma":  ["forma_farmaceutica", "formafarmaceutica"],
    "clase":  ["descripcionatc", "atc"],
    "lab":    ["titular"],
    "via":    ["via_administracion", "viaadministracion"],
    "estado": ["estado_registro", "estadoregistro"],
}


def _primera_col(df, clave):
    return next((c for c in _CANDIDATOS[clave] if c in df.columns), None)


def _normalizar(texto):
    texto = str(texto) if texto is not None and str(texto) != "nan" else ""
    nfkd = unicodedata.normalize("NFKD", texto)
    sin_t = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_t.lower().strip())


def _parsear_concentracion(valor):
    try:
        m = re.search(r"[\d\.]+", str(valor))
        return float(m.group()) if m else 0.0
    except Exception:
        return 0.0


_modelo = None
_df_catalogo = None
_col_map = {}


def cargar_modelo():
    global _modelo, _df_catalogo, _col_map
    model_path = Path(settings.models_dir) / "knn_model.pkl"
    meta_path = Path(settings.models_dir) / "knn_metadata.pkl"

    if not model_path.exists() or not meta_path.exists():
        print("[KNN] Modelo no encontrado. Ejecuta scripts/train_knn.py primero.")
        return False

    _modelo = joblib.load(model_path)
    meta = joblib.load(meta_path)
    _df_catalogo = meta["catalogo"]
    _col_map = meta["col_map"]
    print(f"[KNN] Modelo cargado. Catálogo: {len(_df_catalogo)} medicamentos.")
    return True


def buscar_alternativas(principio_activo, concentracion="", forma_farmaceutica="", k=None):
    if _modelo is None or _df_catalogo is None:
        raise RuntimeError("Modelo KNN no cargado. Llama a cargar_modelo() primero.")

    k = k or settings.knn_k
    pa_norm = _normalizar(principio_activo)

    col_pa = _col_map.get("pa")
    col_conc = _col_map.get("conc")
    col_forma = _col_map.get("forma")
    col_clase = _col_map.get("clase")
    col_nom = _col_map.get("nombre")

    if col_pa:
        cat_pa_norm = _df_catalogo[col_pa].apply(_normalizar)
        equivalentes = _df_catalogo[
            (cat_pa_norm == pa_norm) |
            (cat_pa_norm.str.startswith(pa_norm + " ") & cat_pa_norm.str.contains("equivalente"))
        ].copy()
    else:
        equivalentes = pd.DataFrame()

    if not equivalentes.empty:
        if concentracion and col_conc:
            conc_target = _parsear_concentracion(concentracion)
            equivalentes["_diff"] = equivalentes[col_conc].apply(
                lambda x: abs(_parsear_concentracion(x) - conc_target)
            )
            equivalentes = equivalentes.sort_values("_diff").drop(columns=["_diff"])

        if forma_farmaceutica and col_forma:
            forma_norm = _normalizar(forma_farmaceutica)
            filtrados = equivalentes[equivalentes[col_forma].apply(_normalizar) == forma_norm]
            if not filtrados.empty:
                equivalentes = filtrados

        # deduplicación por nombre normalizado
        if col_nom:
            nombres_norm = equivalentes[col_nom].apply(_normalizar)
            equivalentes = equivalentes[~nombres_norm.duplicated(keep="first")]

        # deduplicación por perfil clínico (concentración + forma)
        # el INVIMA registra el mismo medicamento con nombres distintos,
        # así que usamos concentración+forma para no repetir
        def _clin_key(row):
            conc = _parsear_concentracion(row[col_conc] if col_conc else "")
            forma = _normalizar(row[col_forma] if col_forma else "")
            return (round(conc, 2), forma)

        clin_keys = equivalentes.apply(_clin_key, axis=1)
        equivalentes = equivalentes[~clin_keys.duplicated(keep="first")]

        resultados = []
        vistos = set()

        for _, row in equivalentes.head(k).iterrows():
            item = _fila_a_dict(row, col_nom, col_pa, col_conc, col_forma, col_clase)
            conc_c = str(round(_parsear_concentracion(item.get("concentracion", "")), 2))
            forma_c = _normalizar(item.get("forma_farmaceutica", ""))
            clave = f"{pa_norm}|{conc_c}|{forma_c}"
            if clave in vistos:
                continue
            vistos.add(clave)
            item.update({"nivel": 1, "tipo": "equivalente", "similitud": 100.0})
            resultados.append(item)

        if len(resultados) == 0:
            similares = _knn_vecinos(pa_norm, k)
            for s in similares:
                clave = _normalizar(s.get("nombre", ""))
                if clave in vistos or _normalizar(s.get("principio_activo", "")) == pa_norm:
                    continue
                dist = s.pop("_distancia", 1.0)
                similitud = round(max(0.0, 1.0 - float(dist)) * 100, 1)
                s.update({"nivel": 2, "tipo": "similar_clase", "similitud": similitud})
                resultados.append(s)
                if clave:
                    vistos.add(clave)
                if len(resultados) >= k:
                    break

        return resultados

    similares = _knn_vecinos(pa_norm, k)
    for s in similares:
        dist = s.pop("_distancia", 1.0)
        similitud = round(max(0.0, 1.0 - float(dist)) * 100, 1)
        s.update({"nivel": 2, "tipo": "similar_clase", "similitud": similitud})
    return similares


# valores que el INVIMA usa para campos vacíos
_CODIGOS_INVALIDOS = {"A", "a", "D", "d", "E", "e", "nan", "NaN", "None"}


def _limpiar_pa(pa):
    texto = str(pa) if pa is not None and str(pa) not in _CODIGOS_INVALIDOS else ""
    if not texto:
        return ""
    texto = re.sub(r"\s+equivalente\s+a\s+.*", "", texto, flags=re.IGNORECASE).strip()
    texto = re.sub(r"\s*\(rs=[^)]*\)", "", texto, flags=re.IGNORECASE).strip()
    return texto


def _limpiar_conc(conc):
    texto = str(conc) if conc is not None else ""
    return "" if texto in _CODIGOS_INVALIDOS else texto


def _fila_a_dict(row, col_nom, col_pa, col_conc, col_forma, col_clase):
    col_via = _col_map.get("via")
    col_lab = _col_map.get("lab")
    return {
        "nombre":             str(row.get(col_nom, "")) if col_nom else "",
        "principio_activo":   _limpiar_pa(row.get(col_pa, "") if col_pa else ""),
        "concentracion":      _limpiar_conc(row.get(col_conc, "") if col_conc else ""),
        "forma_farmaceutica": str(row.get(col_forma, "")) if col_forma else "",
        "clase_terapeutica":  str(row.get(col_clase, "")) if col_clase else "",
        "titular":            str(row.get(col_lab, "")) if col_lab else "",
        "via_administracion": str(row.get(col_via, "")) if col_via else "",
    }


def _knn_vecinos(pa_norm, k):
    try:
        meta = joblib.load(Path(settings.models_dir) / "knn_metadata.pkl")
        X = meta["X"]
        col_pa = _col_map.get("pa")
        col_nom = _col_map.get("nombre")
        col_conc = _col_map.get("conc")
        col_forma = _col_map.get("forma")
        col_clase = _col_map.get("clase")

        if not col_pa:
            return []

        cat_pa_norm = _df_catalogo[col_pa].apply(_normalizar)
        fila = _df_catalogo[
            (cat_pa_norm == pa_norm) |
            (cat_pa_norm.str.startswith(pa_norm + " ") & cat_pa_norm.str.contains("equivalente"))
        ].head(1)

        if fila.empty:
            return []

        idx = fila.index[0]
        vector = X[idx].reshape(1, -1)
        n = min(k + 1, len(_df_catalogo))
        distancias, indices = _modelo.kneighbors(vector, n_neighbors=n)

        resultados = []
        seen_claves = set()
        for i, dist in zip(indices[0], distancias[0]):
            if i == idx:
                continue
            row = _df_catalogo.iloc[i]
            item = _fila_a_dict(row, col_nom, col_pa, col_conc, col_forma, col_clase)
            pa_c = _normalizar(item.get("principio_activo", ""))
            conc_c = str(round(_parsear_concentracion(item.get("concentracion", "")), 2))
            forma_c = _normalizar(item.get("forma_farmaceutica", ""))
            clave = f"{pa_c}|{conc_c}|{forma_c}"
            if clave and clave in seen_claves:
                continue
            if clave:
                seen_claves.add(clave)
            item["_distancia"] = round(float(dist), 4)
            resultados.append(item)

        return resultados[:k]
    except Exception as e:
        print(f"[KNN] Error en búsqueda de vecinos: {e}")
        return []


def _build_med_dict(row, score=100.0):
    col_nom = _col_map.get("nombre")
    col_pa = _col_map.get("pa")
    col_conc = _col_map.get("conc")
    col_forma = _col_map.get("forma")
    col_clase = _col_map.get("clase")
    col_via = _col_map.get("via")

    med = {
        "nombre":             str(row.get(col_nom, "")) if col_nom else "",
        "principio_activo":   _limpiar_pa(row.get(col_pa, "") if col_pa else ""),
        "concentracion":      _limpiar_conc(row.get(col_conc, "") if col_conc else ""),
        "forma_farmaceutica": str(row.get(col_forma, "")) if col_forma else "",
        "clase_terapeutica":  str(row.get(col_clase, "")) if col_clase else "",
        "via_administracion": str(row.get(col_via, "")) if col_via else "",
        "titular":            str(row.get("titular", "")) if "titular" in row.index else "",
        "score_match":        round(score, 1),
    }

    for extra_col in ["registrosanitario", "registro_sanitario"]:
        if extra_col in row.index:
            med["registro_sanitario"] = str(row[extra_col])
            break

    if not med["concentracion"]:
        if "cantidad" in row.index and "unidadmedida" in row.index:
            cant = row.get("cantidad", "")
            unid = row.get("unidadmedida", "")
            if cant and str(cant) != "nan" and unid and str(unid) != "nan":
                med["concentracion"] = f"{cant} {unid}"

    for k, v in med.items():
        if str(v) in _CODIGOS_INVALIDOS:
            med[k] = ""

    return med


_pa_unicos_cache = None
_nom_unicos_cache = None


def _get_pa_unicos():
    global _pa_unicos_cache
    if _pa_unicos_cache is not None:
        return _pa_unicos_cache
    col_pa = _col_map.get("pa")
    if not col_pa or _df_catalogo is None:
        return []
    pas = _df_catalogo[col_pa].dropna().unique()
    pairs = [(str(pa), _normalizar(pa)) for pa in pas]
    pairs = [(orig, norm) for orig, norm in pairs if len(norm) >= 4]
    pairs.sort(key=lambda x: -len(x[1]))
    _pa_unicos_cache = pairs
    return pairs


def _get_nom_unicos():
    global _nom_unicos_cache
    if _nom_unicos_cache is not None:
        return _nom_unicos_cache
    col_nom = _col_map.get("nombre")
    if not col_nom or _df_catalogo is None:
        return []
    noms = _df_catalogo[col_nom].dropna().unique()
    pairs = [(str(n), _normalizar(n)) for n in noms]
    pairs = [(orig, norm) for orig, norm in pairs if len(norm) >= 4]
    pairs.sort(key=lambda x: -len(x[1]))
    _nom_unicos_cache = pairs
    return pairs


def identificar_desde_texto(texto_ocr):
    if _df_catalogo is None:
        return None

    texto_norm = _normalizar(texto_ocr)
    if not texto_norm or len(texto_norm) < 3:
        return None

    col_pa = _col_map.get("pa")
    col_nom = _col_map.get("nombre")

    if col_pa:
        for pa_orig, pa_norm in _get_pa_unicos():
            if pa_norm in texto_norm:
                mask = _df_catalogo[col_pa].apply(_normalizar) == pa_norm
                matches = _df_catalogo[mask]
                if not matches.empty:
                    med = _build_med_dict(matches.iloc[0], score=95.0)
                    print(f"[KNN] PA encontrado en texto: '{pa_orig}'")
                    return med

    if col_nom:
        for nom_orig, nom_norm in _get_nom_unicos():
            if nom_norm in texto_norm:
                mask = _df_catalogo[col_nom].apply(_normalizar) == nom_norm
                matches = _df_catalogo[mask]
                if not matches.empty:
                    med = _build_med_dict(matches.iloc[0], score=90.0)
                    print(f"[KNN] Nombre encontrado en texto: '{nom_orig}'")
                    return med

    return None


def buscar_por_nombre(nombre_comercial, umbral=80):
    if _df_catalogo is None:
        return None

    col_nom = _col_map.get("nombre")
    if not col_nom:
        return None

    nombre_norm = _normalizar(nombre_comercial)
    if not nombre_norm or len(nombre_norm) < 3:
        return None

    nombres_catalogo = _df_catalogo[col_nom].apply(_normalizar).tolist()
    resultado = rfprocess.extractOne(nombre_norm, nombres_catalogo, scorer=fuzz.token_set_ratio)

    if resultado is None:
        return None

    _match_text, score, idx = resultado
    umbral_efectivo = umbral if score >= umbral else 70
    if score < umbral_efectivo:
        return None

    row = _df_catalogo.iloc[idx]
    med = _build_med_dict(row, score=score)
    print(f"[KNN] Match: '{nombre_comercial}' → '{med['nombre']}' ({score:.0f}%)")
    return med


def buscar_similares_visual(imagen_path, n_resultados=5):
    try:
        import chromadb
        from PIL import Image
        import torchvision.transforms as T
        import torch

        client = chromadb.PersistentClient(path=str(Path(settings.models_dir).parent / "embeddings_db"))
        collection = client.get_collection("medicamentos_visuales")

        pil_img = Image.open(imagen_path).convert("RGB")
        transform = T.Compose([
            T.Resize((224, 224)),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
        tensor = transform(pil_img).unsqueeze(0)

        import torchvision.models as models
        modelo_cnn = models.efficientnet_b0(weights=None)
        modelo_cnn.classifier = torch.nn.Identity()
        modelo_cnn.eval()

        with torch.no_grad():
            embedding = modelo_cnn(tensor).squeeze().numpy().tolist()

        results = collection.query(
            query_embeddings=[embedding],
            n_results=n_resultados,
            include=["documents", "metadatas", "distances"],
        )

        candidatos = []
        for doc, meta, dist in zip(results["documents"][0], results["metadatas"][0], results["distances"][0]):
            similitud = max(0.0, 1.0 - float(dist))
            candidatos.append({
                "nombre": meta.get("nombre", doc),
                "principio_activo": meta.get("principio_activo", ""),
                "fuente": "cnn_visual",
                "similitud": round(similitud, 4),
            })

        return candidatos
    except Exception as e:
        print(f"[CNN] Error búsqueda visual: {e}")
        return []


def buscar_pa_por_nombre(nombre, threshold=80):
    resultado = buscar_por_nombre(nombre, umbral=threshold)
    if resultado:
        return resultado.get("principio_activo") or None
    return None
