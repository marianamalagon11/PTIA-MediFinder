import re
import unicodedata
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors

from app.config import settings


# ─── COLUMNAS DEL CSV (en orden de prioridad) ────────────────────────────────
# Primero columnas de medicamentos_detallado.csv (apoyo, nombres limpios)
# Luego columnas de medicamentos_invima.csv (fuente principal, nombres pegados)

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


def _primera_col(df: pd.DataFrame, clave: str) -> str | None:
    return next((c for c in _CANDIDATOS[clave] if c in df.columns), None)


def _normalizar(texto) -> str:
    texto = str(texto) if texto is not None and str(texto) != "nan" else ""
    nfkd  = unicodedata.normalize("NFKD", texto)
    sin_t = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_t.lower().strip())


def _parsear_concentracion(valor) -> float:
    try:
        m = re.search(r"[\d\.]+", str(valor))
        return float(m.group()) if m else 0.0
    except Exception:
        return 0.0



_modelo: NearestNeighbors | None = None
_df_catalogo: pd.DataFrame | None = None
_col_map: dict = {}


def cargar_modelo() -> bool:
    global _modelo, _df_catalogo, _col_map
    model_path = Path(settings.models_dir) / "knn_model.pkl"
    meta_path  = Path(settings.models_dir) / "knn_metadata.pkl"

    if not model_path.exists() or not meta_path.exists():
        print("[KNN] Modelo no encontrado. Ejecuta scripts/train_knn.py primero.")
        return False

    _modelo      = joblib.load(model_path)
    meta         = joblib.load(meta_path)
    _df_catalogo = meta["catalogo"]
    _col_map     = meta["col_map"]
    print(f"[KNN] Modelo cargado. Catálogo: {len(_df_catalogo)} medicamentos.")
    return True



def buscar_alternativas(
    principio_activo: str,
    concentracion: str = "",
    forma_farmaceutica: str = "",
    k: int | None = None,
) -> list[dict]:
    """
    Dado un principio activo (y opcionalmente concentración/forma),
    retorna los K medicamentos más similares del catálogo.

    Cada resultado incluye:
      - campos del CSV (nombre, PA, concentración, forma, ATC, titular, etc.)
      - 'nivel': 1 = equivalente (mismo PA), 2 = similar por clase terapéutica (ATC)
      - 'tipo': 'equivalente' | 'similar_clase'
    """
    if _modelo is None or _df_catalogo is None:
        raise RuntimeError("Modelo KNN no cargado. Llama a cargar_modelo() primero.")

    k       = k or settings.knn_k
    pa_norm = _normalizar(principio_activo)

    col_pa    = _col_map.get("pa")
    col_conc  = _col_map.get("conc")
    col_forma = _col_map.get("forma")
    col_clase = _col_map.get("clase")
    col_nom   = _col_map.get("nombre")

    if col_pa:
        equivalentes = _df_catalogo[
            _df_catalogo[col_pa].apply(_normalizar) == pa_norm
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
            filtrados  = equivalentes[
                equivalentes[col_forma].apply(_normalizar) == forma_norm
            ]
            if not filtrados.empty:
                equivalentes = filtrados

        resultados = []
        for _, row in equivalentes.head(k).iterrows():
            item = _fila_a_dict(row, col_nom, col_pa, col_conc, col_forma, col_clase)
            item.update({"nivel": 1, "tipo": "equivalente"})
            resultados.append(item)

        if len(resultados) < k:
            faltantes  = k - len(resultados)
            names_ya   = {r.get("nombre", "") for r in resultados}
            similares  = _knn_vecinos(pa_norm, faltantes + len(resultados))
            for s in similares:
                if s.get("nombre", "") not in names_ya and _normalizar(s.get("principio_activo", "")) != pa_norm:
                    s.update({"nivel": 2, "tipo": "similar_clase"})
                    resultados.append(s)
                if len(resultados) >= k:
                    break

        return resultados

    similares = _knn_vecinos(pa_norm, k)
    for s in similares:
        s.update({"nivel": 2, "tipo": "similar_clase"})
    return similares


def _fila_a_dict(row, col_nom, col_pa, col_conc, col_forma, col_clase) -> dict:
    """Convierte una fila del DataFrame en un dict con claves estables."""
    return {
        "nombre":           row.get(col_nom, "") if col_nom else "",
        "principio_activo": row.get(col_pa, "")  if col_pa  else "",
        "concentracion":    row.get(col_conc, "") if col_conc else "",
        "forma_farmaceutica": row.get(col_forma, "") if col_forma else "",
        "clase_terapeutica":  row.get(col_clase, "") if col_clase else "",
        "titular": row.get("titular", "") if "titular" in row.index else "",
    }


def _knn_vecinos(pa_norm: str, k: int) -> list[dict]:
    """Usa el modelo NearestNeighbors para buscar los vecinos más cercanos."""
    try:
        meta    = joblib.load(Path(settings.models_dir) / "knn_metadata.pkl")
        X       = meta["X"]
        col_pa  = _col_map.get("pa")
        col_nom = _col_map.get("nombre")
        col_conc  = _col_map.get("conc")
        col_forma = _col_map.get("forma")
        col_clase = _col_map.get("clase")

        if not col_pa:
            return []

        fila = _df_catalogo[
            _df_catalogo[col_pa].apply(_normalizar) == pa_norm
        ].head(1)

        if fila.empty:
            return []

        idx    = fila.index[0]
        vector = X[idx].reshape(1, -1)

        n = min(k + 1, len(_df_catalogo))
        distancias, indices = _modelo.kneighbors(vector, n_neighbors=n)

        resultados = []
        for i, dist in zip(indices[0], distancias[0]):
            if i == idx:
                continue
            row  = _df_catalogo.iloc[i]
            item = _fila_a_dict(row, col_nom, col_pa, col_conc, col_forma, col_clase)
            item["_distancia"] = round(float(dist), 4)
            resultados.append(item)

        return resultados[:k]
    except Exception as e:
        print(f"[KNN] Error en búsqueda de vecinos: {e}")
        return []