import os
import tempfile
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import settings
from app.ml import (
    buscar_alternativas,
    buscar_pa_por_nombre,
    buscar_por_nombre,
    buscar_similares_visual,
    explicar_compuesto,
    extraer_texto_imagen,
)

router = APIRouter(prefix="/medifinder", tags=["MediFinder"])


class OCRResult(BaseModel):
    texto_completo: str
    nombre_detectado: Optional[str]
    nombre_normalizado: Optional[str]
    confianza: float
    ocr_exitoso: bool
    principio_activo: Optional[str] = None
    metodo: Optional[str] = None
    match_score: Optional[float] = None


class CandidatoVisual(BaseModel):
    nombre: str
    principio_activo: str
    fuente: str
    similitud: float


class Alternativa(BaseModel):
    nombre: Optional[str] = None
    principio_activo: Optional[str] = None
    concentracion: Optional[str] = None
    forma_farmaceutica: Optional[str] = None
    laboratorio: Optional[str] = None
    nivel: int
    tipo: str
    clase_terapeutica: Optional[str] = None
    titular: Optional[str] = None
    via_administracion: Optional[str] = None
    similitud: Optional[float] = None


class ExplicacionCompuesto(BaseModel):
    principio_activo: str
    explicacion: str
    fuente_kb: bool


class AnalisisCompleto(BaseModel):
    metodo_identificacion: str
    ocr: Optional[OCRResult]
    candidatos_visuales: list[CandidatoVisual]
    principio_activo_identificado: Optional[str]
    alternativas: list[Alternativa]
    explicacion: Optional[ExplicacionCompuesto]


@router.post("/ocr", response_model=OCRResult, summary="Extrae texto de una imagen de medicamento")
async def endpoint_ocr(imagen: UploadFile = File(...)):
    """Paso 1 del pipeline: OCR sobre la imagen del empaque/blíster."""
    contenido = await imagen.read()
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(contenido)
        tmp_path = tmp.name

    try:
        resultado = extraer_texto_imagen(tmp_path)
    finally:
        os.unlink(tmp_path)

    if "error" in resultado:
        raise HTTPException(status_code=422, detail=resultado["error"])

    # Si el OCR tuvo éxito, buscar el principio activo en el catálogo INVIMA
    if resultado.get("ocr_exitoso") and resultado.get("nombre_normalizado"):
        try:
            med = buscar_por_nombre(resultado["nombre_normalizado"], umbral=70)
            if med:
                resultado["principio_activo"] = med.get("principio_activo") or None
                resultado["match_score"]      = med.get("score_match")
                resultado["metodo"]           = "ocr"
        except Exception:
            pass

    if not resultado.get("metodo"):
        resultado["metodo"] = "ocr"

    return OCRResult(**resultado)


@router.post("/alternativas", response_model=list[Alternativa], summary="Busca alternativas por principio activo (KNN)")
async def endpoint_alternativas(
    principio_activo: str = Form(...),
    concentracion: str = Form(""),
    forma_farmaceutica: str = Form(""),
    k: int = Form(5),
):
    """Paso 3 del pipeline: KNN para encontrar medicamentos alternativos."""
    try:
        alternativas = buscar_alternativas(
            principio_activo=principio_activo,
            concentracion=concentracion,
            forma_farmaceutica=forma_farmaceutica,
            k=k,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return [Alternativa(**{k: v for k, v in alt.items() if k in Alternativa.model_fields}) for alt in alternativas]


@router.post("/explicar", response_model=ExplicacionCompuesto, summary="Explica un principio activo con LLM")
async def endpoint_explicar(principio_activo: str = Form(...)):
    """Genera una explicación completa del principio activo usando RAG + Claude."""
    try:
        resultado = explicar_compuesto(principio_activo)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return ExplicacionCompuesto(**resultado)


@router.post("/analizar", response_model=AnalisisCompleto, summary="Pipeline completo: imagen → OCR/CNN → KNN → LLM")
async def endpoint_analizar(
    imagen: UploadFile = File(...),
    incluir_explicacion: bool = Form(True),
    k_alternativas: int = Form(5),
):
    contenido = await imagen.read()

    # Usar la extensión real del archivo subido para que PIL lo reconozca correctamente
    from pathlib import Path as _Path
    suffix = _Path(imagen.filename).suffix if imagen.filename else ".jpg"
    if not suffix:
        suffix = ".jpg"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(contenido)
        tmp.flush()
        tmp_path = tmp.name

    ocr_result: dict = {}
    try:
        ocr_result      = extraer_texto_imagen(tmp_path)
        candidatos_vis  = []
        pa_identificado = None
        metodo          = "fallback"

        # CNN siempre se intenta para tener candidatos visuales disponibles
        try:
            candidatos_vis = buscar_similares_visual(tmp_path, n_resultados=5)
        except Exception as e:
            print(f"[PIPELINE] CNN no disponible: {e}")

        confianza   = ocr_result.get("confianza", 0)
        ocr_exitoso = ocr_result.get("ocr_exitoso", False)
        ocr_con_error = "error" in ocr_result

        if not ocr_con_error and ocr_exitoso and confianza >= settings.ocr_confidence_threshold:
            metodo = "ocr"
            nombre_norm = ocr_result.get("nombre_normalizado", "")
            try:
                pa_identificado = buscar_pa_por_nombre(nombre_norm)
            except Exception as e:
                print(f"[PIPELINE] Error lookup nombre→PA: {e}")
                pa_identificado = None

            if not pa_identificado and candidatos_vis:
                pa_identificado = candidatos_vis[0]["principio_activo"]
                metodo = "ocr+cnn"

        elif not ocr_con_error and ocr_exitoso:
            metodo = "ocr_bajo_conf"
            nombre_norm = ocr_result.get("nombre_normalizado", "")
            try:
                pa_identificado = buscar_pa_por_nombre(nombre_norm, threshold=65)
            except Exception:
                pa_identificado = None

            if not pa_identificado and candidatos_vis:
                pa_identificado = candidatos_vis[0]["principio_activo"]
                metodo = "cnn"

        else:
            metodo = "cnn"
            if candidatos_vis:
                pa_identificado = candidatos_vis[0]["principio_activo"]

        alternativas = []
        if pa_identificado:
            try:
                alts_raw = buscar_alternativas(pa_identificado, k=k_alternativas)
                alternativas = [
                    Alternativa(**{k: v for k, v in alt.items() if k in Alternativa.model_fields})
                    for alt in alts_raw
                ]
            except Exception as e:
                print(f"[PIPELINE] Error KNN: {e}")

        explicacion = None
        if incluir_explicacion and pa_identificado:
            try:
                exp_raw     = explicar_compuesto(pa_identificado)
                explicacion = ExplicacionCompuesto(**exp_raw)
            except Exception as e:
                print(f"[PIPELINE] Error LLM: {e}")

    finally:
        os.unlink(tmp_path)

    # Solo construir OCRResult si el OCR no tuvo error y tiene todos los campos
    ocr_model = None
    if ocr_result and "error" not in ocr_result and "texto_completo" in ocr_result:
        ocr_model = OCRResult(**ocr_result)

    return AnalisisCompleto(
        metodo_identificacion=metodo,
        ocr=ocr_model,
        candidatos_visuales=[CandidatoVisual(**c) for c in candidatos_vis],
        principio_activo_identificado=pa_identificado,
        alternativas=alternativas,
        explicacion=explicacion,
    )