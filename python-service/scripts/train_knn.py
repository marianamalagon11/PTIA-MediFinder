"""
Entrena el modelo KNN con medicamentos_invima.csv (fuente principal).
Guarda modelo + metadata en models/medifinder/.

Ejecutar: python scripts/train_knn.py
"""

import re
import sys
import unicodedata
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import LabelEncoder, MinMaxScaler

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.config import settings



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


def main():
    output_dir = Path(settings.models_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_invima    = Path(settings.csv_invima)
    csv_detallado = Path(settings.csv_medicamentos)

    if csv_invima.exists():
        csv_path = csv_invima
        print(f"[TRAIN] Fuente principal: {csv_path}")
    elif csv_detallado.exists():
        csv_path = csv_detallado
        print(f"[TRAIN] Fuente fallback (detallado): {csv_path}")
    else:
        print("[ERROR] No se encontró ningún CSV de medicamentos.")
        print(f"  Buscado en: {csv_invima} y {csv_detallado}")
        sys.exit(1)

    df = pd.read_csv(csv_path, encoding="utf-8-sig", low_memory=False)
    print(f"[TRAIN] {len(df)} registros cargados.")
    print(f"[TRAIN] Columnas: {list(df.columns)}")

    col_map = {clave: _primera_col(df, clave) for clave in _CANDIDATOS}
    print("\n[TRAIN] Columnas mapeadas:")
    for k, v in col_map.items():
        estado = "✓" if v else "✗ (no disponible)"
        print(f"  {k:8} → {v or '—':35} {estado}")

    col_pa = col_map["pa"]
    if not col_pa:
        print(f"\n[ERROR] No se encontró columna de principio activo.")
        print(f"  Columnas disponibles: {list(df.columns)}")
        sys.exit(1)

    df[col_pa] = df[col_pa].apply(_normalizar)
    df = df[df[col_pa].str.len() > 0].copy()
    print(f"\n[TRAIN] {len(df)} registros tras limpiar principio activo vacío.")

    col_estado = col_map["estado"]
    if col_estado:
        df_activos = df[df[col_estado].apply(_normalizar).isin(["vigente", "activo", "1"])]
        if len(df_activos) > 100:
            df = df_activos.copy()
            print(f"[TRAIN] {len(df)} registros con estado activo/vigente.")

    features = []

    le_pa = LabelEncoder()
    df["_pa_enc"] = le_pa.fit_transform(df[col_pa])
    features.append("_pa_enc")
    print(f"\n[TRAIN] Principios activos únicos: {df[col_pa].nunique()}")

    col_conc = col_map["conc"]
    scaler_conc = None
    if col_conc:
        df["_conc_num"]  = df[col_conc].apply(_parsear_concentracion)
        scaler_conc = MinMaxScaler()
        df["_conc_norm"] = scaler_conc.fit_transform(df[["_conc_num"]])
        features.append("_conc_norm")
    else:
        print("[TRAIN] Sin concentración → feature omitido.")

    col_forma = col_map["forma"]
    le_forma  = None
    if col_forma:
        df[col_forma] = df[col_forma].apply(_normalizar).fillna("desconocido")
        le_forma = LabelEncoder()
        df["_forma_enc"] = le_forma.fit_transform(df[col_forma])
        features.append("_forma_enc")
    else:
        print("[TRAIN] Sin forma farmacéutica → feature omitido.")

    col_clase = col_map["clase"]
    le_clase  = None
    if col_clase:
        df[col_clase] = df[col_clase].apply(_normalizar).fillna("desconocido")
        le_clase = LabelEncoder()
        df["_clase_enc"] = le_clase.fit_transform(df[col_clase])
        features.append("_clase_enc")
    else:
        print("[TRAIN] Sin clase terapéutica (ATC) → feature omitido.")

    col_via = col_map["via"]
    le_via  = None
    if col_via:
        df[col_via] = df[col_via].apply(_normalizar).fillna("desconocido")
        le_via = LabelEncoder()
        df["_via_enc"] = le_via.fit_transform(df[col_via])
        features.append("_via_enc")

    X = df[features].values.astype(float)
    print(f"[TRAIN] Feature matrix: {X.shape} ({len(features)} features)")

    k_vecinos = min(settings.knn_k + 10, len(df) - 1)
    modelo = NearestNeighbors(
        n_neighbors=k_vecinos,
        metric="euclidean",
        algorithm="ball_tree",
        n_jobs=-1,
    )
    modelo.fit(X)
    print(f"[TRAIN] NearestNeighbors entrenado — k={k_vecinos}.")

    joblib.dump(modelo, output_dir / "knn_model.pkl")
    joblib.dump({
        "catalogo":  df.reset_index(drop=True),
        "col_map":   col_map,
        "X":         X,
        "features":  features,
        "encoders":  {"pa": le_pa, "forma": le_forma, "clase": le_clase, "via": le_via},
        "scalers":   {"conc": scaler_conc},
    }, output_dir / "knn_metadata.pkl")

    print(f"\nModelo KNN guardado en {output_dir}/")
    print(f"   Registros entrenados:      {len(df)}")
    print(f"   Principios activos únicos: {df[col_pa].nunique()}")


if __name__ == "__main__":
    main()