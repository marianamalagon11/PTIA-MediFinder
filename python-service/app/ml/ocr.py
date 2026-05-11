import re
import unicodedata
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def _preprocesar(imagen: np.ndarray) -> np.ndarray:
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gris = clahe.apply(gris)

    gris = cv2.fastNlMeansDenoising(gris, h=10)

    binaria = cv2.adaptiveThreshold(
        gris, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )
    return binaria


def _corregir_rotacion(imagen: np.ndarray) -> np.ndarray:
    """Corrige inclinación usando el ángulo detectado por Tesseract OSD."""
    try:
        gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
        osd = pytesseract.image_to_osd(gris, output_type=pytesseract.Output.DICT)
        angulo = osd.get("rotate", 0)
        if angulo != 0:
            h, w = imagen.shape[:2]
            centro = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(centro, -angulo, 1.0)
            imagen = cv2.warpAffine(imagen, M, (w, h), flags=cv2.INTER_CUBIC)
    except Exception:
        pass
    return imagen


def _normalizar_texto(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in nfkd if not unicodedata.combining(c))
    limpio = re.sub(r"[^a-z0-9\s\-\/\.]", "", sin_tildes.lower())
    return re.sub(r"\s+", " ", limpio).strip()


def _extraer_nombre_medicamento(texto: str) -> str | None:
    """
    Heurística simple: la primera línea con más de 3 caracteres suele ser
    el nombre del medicamento en un empaque. Ajustable según resultados reales.
    """
    lineas = [l.strip() for l in texto.split("\n") if len(l.strip()) > 3]
    if not lineas:
        return None

    patron_descartar = re.compile(r"^(lote|lot|exp|vence|reg|invima|\d{2}[\/\-]\d{2})", re.I)
    candidatos = [l for l in lineas if not patron_descartar.match(l)]

    return candidatos[0] if candidatos else lineas[0]



def extraer_texto_imagen(imagen_path: str) -> dict:
    """
    Recibe el path de una imagen y retorna:
    {
        "texto_completo": str,
        "nombre_detectado": str | None,
        "nombre_normalizado": str | None,
        "confianza": float,      # 0-100, promedio de confianza de Tesseract
        "ocr_exitoso": bool,
    }
    """
    try:
        pil_img = Image.open(imagen_path).convert("RGB")
        img_cv  = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    except Exception as e:
        return {"error": f"No se pudo abrir la imagen: {e}", "ocr_exitoso": False}

    img_cv = _corregir_rotacion(img_cv)
    img_pp = _preprocesar(img_cv)

    config = "--oem 3 --psm 6"
    try:
        data = pytesseract.image_to_data(
            img_pp,
            lang="spa+eng",
            config=config,
            output_type=pytesseract.Output.DICT,
        )
    except Exception:
        data = pytesseract.image_to_data(
            img_pp,
            lang="eng",
            config=config,
            output_type=pytesseract.Output.DICT,
        )

    palabras     = [w for w, c in zip(data["text"], data["conf"]) if int(c) > 0 and w.strip()]
    confianzas   = [int(c) for c in data["conf"] if int(c) > 0]
    texto_completo = " ".join(palabras)
    confianza_prom = sum(confianzas) / len(confianzas) if confianzas else 0

    nombre = _extraer_nombre_medicamento(texto_completo)
    nombre_norm = _normalizar_texto(nombre) if nombre else None

    return {
        "texto_completo":   texto_completo,
        "nombre_detectado": nombre,
        "nombre_normalizado": nombre_norm,
        "confianza":        round(confianza_prom, 1),
        "ocr_exitoso":      confianza_prom >= 40 and bool(nombre),
    }