import platform
import re
import unicodedata

import cv2
import numpy as np
import pytesseract
from PIL import Image

if platform.system() == "Windows":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

_STOPWORDS_OCR = {
    "medicamento", "medicamentos", "ficticio", "ficticia",
    "comprimido", "comprimidos", "tableta", "tabletas",
    "capsula", "capsulas", "suspension", "solucion",
    "inyectable", "ampollas", "frasco", "caja", "grupo",
    "adultos", "ninos", "pediatrico", "via", "oral",
    "unidades", "polvo", "esteril", "liofilizado",
}


def _escalar(imagen: np.ndarray, factor: float = 2.0) -> np.ndarray:
    h, w = imagen.shape[:2]
    return cv2.resize(imagen, (int(w * factor), int(h * factor)), interpolation=cv2.INTER_CUBIC)


def _preprocesar_agresivo(imagen: np.ndarray) -> np.ndarray:
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


def _preprocesar_suave(imagen: np.ndarray) -> np.ndarray:
    """Solo escala de grises + umbral Otsu, menos destructivo para empaques de color."""
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
    gris = cv2.GaussianBlur(gris, (3, 3), 0)
    _, binaria = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binaria


def _preprocesar_canales_color(imagen: np.ndarray) -> list[np.ndarray]:
    """
    Retorna versiones procesadas de canales individuales de color.
    Útil para capturar texto amarillo/rojo sobre fondos de color intenso.
    """
    resultados = []
    try:
        b, g, r = cv2.split(imagen)

        # Canal rojo: resalta texto rojo/amarillo sobre fondos azules
        _, bin_r = cv2.threshold(r, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        resultados.append(bin_r)

        # Diferencia R-B: amplifica amarillo/rojo contra azul
        diff = cv2.subtract(r, b)
        _, bin_diff = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        resultados.append(bin_diff)
    except Exception:
        pass
    return resultados


def _corregir_rotacion(imagen: np.ndarray) -> np.ndarray:
    """
    Prueba las 4 rotaciones cardinales y retorna la imagen en la orientación
    que produce mayor confianza OCR. Más robusto que OSD para empaques
    con texto en múltiples direcciones.
    """
    rotaciones = [
        imagen,
        cv2.rotate(imagen, cv2.ROTATE_90_COUNTERCLOCKWISE),
        cv2.rotate(imagen, cv2.ROTATE_180),
        cv2.rotate(imagen, cv2.ROTATE_90_CLOCKWISE),
    ]

    mejor_conf = -1.0
    mejor_img  = imagen

    for img_rot in rotaciones:
        try:
            gris = cv2.cvtColor(img_rot, cv2.COLOR_BGR2GRAY)
            data = pytesseract.image_to_data(
                gris, lang="spa+eng",
                config="--oem 3 --psm 3",
                output_type=pytesseract.Output.DICT,
            )
            confianzas = [int(c) for c in data["conf"] if int(c) > 0]
            conf = sum(confianzas) / len(confianzas) if confianzas else 0.0
            if conf > mejor_conf:
                mejor_conf = conf
                mejor_img  = img_rot
        except Exception:
            continue

    return mejor_img


def _normalizar_texto(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in nfkd if not unicodedata.combining(c))
    limpio = re.sub(r"[^a-z0-9\s\-\/\.]", "", sin_tildes.lower())
    return re.sub(r"\s+", " ", limpio).strip()


def _es_nombre_medicamento_valido(texto: str) -> bool:
    """Retorna False si el texto es solo terminología genérica farmacéutica."""
    palabras = set(re.sub(r"[^a-z\s]", "", texto.lower()).split())
    palabras_significativas = palabras - _STOPWORDS_OCR
    return bool(palabras_significativas) and any(len(p) >= 4 for p in palabras_significativas)


def _extraer_nombre_medicamento(texto: str) -> str | None:
    lineas = [l.strip() for l in texto.split("\n") if len(l.strip()) > 3]
    if not lineas:
        return None

    patron_descartar = re.compile(
        r"^(lote|lot|exp|vence|reg|invima|\d{2}[\/\-]\d{2}|fabricado|contenido"
        r"|dosis|adultos|ninos|via|vía|oral|topico|tableta|capsula|mg\b|ml\b)",
        re.I
    )

    def score_linea(linea: str) -> float:
        letras = sum(c.isalpha() for c in linea)
        return letras / max(len(linea), 1)

    candidatos = [
        l for l in lineas
        if not patron_descartar.match(l) and _es_nombre_medicamento_valido(l)
    ]

    if candidatos:
        return max(candidatos, key=score_linea)

    candidatos_basico = [l for l in lineas if not patron_descartar.match(l)]
    return candidatos_basico[0] if candidatos_basico else lineas[0]


def _ocr_sobre_imagen(img_np: np.ndarray, config: str) -> dict:
    """Ejecuta OCR, intenta spa+eng y cae a eng si falla."""
    for lang in ("spa+eng", "eng"):
        try:
            data = pytesseract.image_to_data(
                img_np, lang=lang, config=config,
                output_type=pytesseract.Output.DICT,
            )
            palabras   = [w for w, c in zip(data["text"], data["conf"]) if int(c) > 0 and w.strip()]
            confianzas = [int(c) for c in data["conf"] if int(c) > 0]
            texto = " ".join(palabras)
            conf  = sum(confianzas) / len(confianzas) if confianzas else 0.0
            return {"texto": texto, "confianza": round(conf, 1)}
        except Exception:
            continue
    return {"texto": "", "confianza": 0.0}


def extraer_texto_imagen(imagen_path: str) -> dict:
    """
    Recibe el path de una imagen y retorna:
    {
        "texto_completo": str,
        "nombre_detectado": str | None,
        "nombre_normalizado": str | None,
        "confianza": float,
        "ocr_exitoso": bool,
    }
    """
    try:
        pil_img = Image.open(imagen_path).convert("RGB")
        img_cv  = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    except Exception as e:
        return {"error": f"No se pudo abrir la imagen: {e}", "ocr_exitoso": False}

    img_cv       = _corregir_rotacion(img_cv)
    img_escalada = _escalar(img_cv, 2.0)
    img_suave    = _preprocesar_suave(img_escalada)
    img_agresivo = _preprocesar_agresivo(img_escalada)

    intentos = [
        (img_suave,    "--oem 3 --psm 11"),  # sparse text — mejor para empaques variados
        (img_suave,    "--oem 3 --psm 3"),   # auto segmentación
        (img_agresivo, "--oem 3 --psm 6"),   # bloque uniforme
        (img_agresivo, "--oem 3 --psm 4"),   # columna única
    ]

    # Intentos adicionales con canales de color (texto amarillo/rojo sobre fondo de color)
    for img_canal in _preprocesar_canales_color(img_escalada):
        intentos.append((img_canal, "--oem 3 --psm 11"))
        intentos.append((img_canal, "--oem 3 --psm 3"))

    mejor = {"texto": "", "confianza": 0.0}
    for img_intento, cfg in intentos:
        r = _ocr_sobre_imagen(img_intento, cfg)
        if r["confianza"] > mejor["confianza"] and len(r["texto"].strip()) > 3:
            mejor = r

    texto_completo = mejor["texto"]
    confianza_prom = mejor["confianza"]

    nombre      = _extraer_nombre_medicamento(texto_completo) if texto_completo else None
    nombre_norm = _normalizar_texto(nombre) if nombre else None

    return {
        "texto_completo":    texto_completo,
        "nombre_detectado":  nombre,
        "nombre_normalizado": nombre_norm,
        "confianza":         confianza_prom,
        "ocr_exitoso":       confianza_prom >= 40 and bool(nombre),
    }