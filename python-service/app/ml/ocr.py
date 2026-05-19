import platform
import re
import unicodedata

import cv2
import numpy as np
import pytesseract
from PIL import Image

if platform.system() == "Windows":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# palabras genéricas que no sirven como nombre del medicamento
_STOPWORDS_OCR = {
    "medicamento", "medicamentos", "comprimido", "comprimidos",
    "tableta", "tabletas", "capsula", "capsulas", "suspension",
    "solucion", "inyectable", "ampollas", "frasco", "caja",
    "adultos", "ninos", "via", "oral", "unidades", "polvo",
}


def _escalar_si_pequena(img, min_lado=1000):
    h, w = img.shape[:2]
    if min(h, w) < min_lado:
        factor = min_lado / min(h, w)
        img = cv2.resize(img, (int(w * factor), int(h * factor)), interpolation=cv2.INTER_CUBIC)
    return img


def _nitidez(img):
    blur = cv2.GaussianBlur(img, (0, 0), 3)
    return cv2.addWeighted(img, 1.5, blur, -0.5, 0)


def _preprocesar_binario(img_cv):
    gris = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gris = clahe.apply(gris)
    gris = cv2.fastNlMeansDenoising(gris, h=10)
    return cv2.adaptiveThreshold(gris, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)


def _preprocesar_clahe(img_gris):
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    return _nitidez(clahe.apply(img_gris))


def _preprocesar_otsu(img_gris):
    sharp = _nitidez(img_gris)
    _, binaria = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binaria


def _preprocesar_gris_nitido(img_gris):
    return _nitidez(img_gris)


def _preprocesar_invertido(img_gris):
    # útil para cajas con texto claro sobre fondo oscuro
    invertido = cv2.bitwise_not(img_gris)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(invertido)
    denoised = cv2.fastNlMeansDenoising(enhanced, h=10)
    return cv2.adaptiveThreshold(denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)


def _preprocesar_bilateral(img_gris):
    # bilateral filter conserva bordes mejor en fotos borrosas
    filtrado = cv2.bilateralFilter(img_gris, 9, 75, 75)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enhanced = clahe.apply(filtrado)
    _, binaria = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binaria


def _corregir_rotacion(imagen):
    try:
        gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
        osd = pytesseract.image_to_osd(gris, config="--psm 0", output_type=pytesseract.Output.DICT)
        angulo = int(osd.get("rotate", 0))
        if angulo == 90:
            return cv2.rotate(imagen, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif angulo == 180:
            return cv2.rotate(imagen, cv2.ROTATE_180)
        elif angulo == 270:
            return cv2.rotate(imagen, cv2.ROTATE_90_CLOCKWISE)
    except Exception:
        pass
    return imagen


def _normalizar_texto(texto):
    nfkd = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in nfkd if not unicodedata.combining(c))
    limpio = re.sub(r"[^a-z0-9\s\-\/\.]", "", sin_tildes.lower())
    return re.sub(r"\s+", " ", limpio).strip()


def _limpiar_nombre(texto):
    limpio = re.sub(r"[^A-Za-z0-9\s\-\/\.À-ɏ]", "", texto)
    return re.sub(r"\s+", " ", limpio).strip()


def _extraer_nombre_medicamento(texto):
    # las líneas ya vienen ordenadas de mayor a menor tamaño de letra
    lineas = [l.strip() for l in texto.split("\n") if len(l.strip()) > 2]
    if not lineas:
        return None

    patron_descartar = re.compile(
        r"^(lote|lot|exp|vence|reg|invima|fabricado|manufactured|"
        r"conserve|store|mantener|via|via oral|tableta|capsula|"
        r"\d{2}[\/\-]\d{2}|\d{4}|www\.|http|ml$|mg$|[a-z]{1,3}$)",
        re.I,
    )

    def tiene_letras(linea):
        return len([c for c in linea if c.isalpha()]) >= 4

    candidatos = [l for l in lineas if not patron_descartar.match(l) and tiene_letras(l)]
    if not candidatos:
        candidatos = [l for l in lineas if tiene_letras(l)]
    if not candidatos:
        return lineas[0]

    top = candidatos[0]

    # si el nombre está partido en dos líneas cortas (ej. "BUSCAPINA / COMPOSITUM")
    if len(candidatos) >= 2 and len(top) < 20:
        segundo = candidatos[1]
        letras2 = [c for c in segundo if c.isalpha()]
        if letras2 and len(segundo) < 20:
            ratio2 = sum(1 for c in letras2 if c.isupper()) / len(letras2)
            if ratio2 >= 0.7:
                top = f"{top} {segundo}"

    return _limpiar_nombre(top) or top


def _ocr_con_psm(img_pp, psm):
    config = f"--oem 3 --psm {psm}"
    for lang in ("spa+eng", "eng"):
        try:
            data = pytesseract.image_to_data(
                img_pp, lang=lang, config=config,
                output_type=pytesseract.Output.DICT,
            )
            lineas = {}
            confianzas = []
            for word, conf, block, par, line, h in zip(
                data["text"], data["conf"],
                data["block_num"], data["par_num"], data["line_num"],
                data["height"],
            ):
                c = int(conf)
                if c > 0 and word.strip():
                    key = (block, par, line)
                    if key not in lineas:
                        lineas[key] = {"words": [], "max_h": 0}
                    lineas[key]["words"].append(word)
                    lineas[key]["max_h"] = max(lineas[key]["max_h"], int(h))
                    confianzas.append(c)

            # ordenar de mayor a menor tamaño para que el nombre quede primero
            ordenadas = sorted(lineas.values(), key=lambda x: x["max_h"], reverse=True)
            texto = "\n".join(" ".join(l["words"]) for l in ordenadas)
            conf = sum(confianzas) / len(confianzas) if confianzas else 0.0
            return {"texto": texto, "confianza": round(conf, 1)}
        except Exception:
            continue
    return {"texto": "", "confianza": 0.0}


def extraer_texto_imagen(imagen_path):
    try:
        pil_img = Image.open(imagen_path).convert("RGB")
        img_cv = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    except Exception as e:
        return {"error": f"No se pudo abrir la imagen: {e}", "ocr_exitoso": False}

    img_cv = _escalar_si_pequena(img_cv)
    img_cv = _corregir_rotacion(img_cv)
    img_gris = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)

    # probar 6 formas de preprocesar × 4 modos PSM = 24 combinaciones
    variantes = [
        _preprocesar_binario(img_cv),
        _preprocesar_clahe(img_gris),
        _preprocesar_otsu(img_gris),
        _preprocesar_gris_nitido(img_gris),
        _preprocesar_invertido(img_gris),
        _preprocesar_bilateral(img_gris),
    ]

    mejor = {"texto": "", "confianza": 0.0}
    for img_pp in variantes:
        for psm in (6, 3, 11, 7):
            r = _ocr_con_psm(img_pp, psm)
            if r["confianza"] > mejor["confianza"] and len(r["texto"].strip()) > 3:
                mejor = r

    texto_completo = mejor["texto"]
    confianza = mejor["confianza"]
    nombre = _extraer_nombre_medicamento(texto_completo) if texto_completo else None
    nombre_norm = _normalizar_texto(nombre) if nombre else None

    return {
        "texto_completo": texto_completo,
        "nombre_detectado": nombre,
        "nombre_normalizado": nombre_norm,
        "confianza": confianza,
        "ocr_exitoso": confianza >= 40 and bool(nombre),
    }
