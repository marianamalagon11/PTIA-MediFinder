import os
import tempfile
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import settings
from app.ml import (
    buscar_alternativas,
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
    """
    Pipeline completo de MediFinder:
    1. OCR sobre la imagen
    2. Si OCR falla → CNN fallback (búsqueda visual en ChromaDB)
    3. KNN para alternativas por principio activo
    4. LLM para explicación del compuesto
    """
    contenido = await imagen.read()
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(contenido)
        tmp_path = tmp.name

    try:
        ocr_result      = extraer_texto_imagen(tmp_path)
        candidatos_vis  = []
        pa_identificado = None
        metodo          = "fallback"

        if ocr_result.get("ocr_exitoso") and ocr_result.get("confianza", 0) >= settings.ocr_confidence_threshold:

            metodo = "ocr"

            nombre_norm = ocr_result.get("nombre_normalizado", "")
            try:
                resultados_nombre = buscar_alternativas(nombre_norm, k=1)
                if resultados_nombre:
                    from app.ml.knn import _col_map, _df_catalogo, _normalizar
                    col_pa = _col_map.get("pa")
                    if col_pa:
                        pa_identificado = resultados_nombre[0].get(col_pa)
            except Exception:
                pa_identificado = nombre_norm 

        else:

            metodo = "cnn"
            try:
                candidatos_vis = buscar_similares_visual(tmp_path, n_resultados=5)
                if candidatos_vis:
                    pa_identificado = candidatos_vis[0]["principio_activo"]
            except Exception as e:
                print(f"[PIPELINE] Error CNN: {e}")

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
                exp_raw    = explicar_compuesto(pa_identificado)
                explicacion = ExplicacionCompuesto(**exp_raw)
            except Exception as e:
                print(f"[PIPELINE] Error LLM: {e}")

    finally:
        os.unlink(tmp_path)

    return AnalisisCompleto(
        metodo_identificacion=metodo,
        ocr=OCRResult(**ocr_result) if "ocr_exitoso" in ocr_result else None,
        candidatos_visuales=[CandidatoVisual(**c) for c in candidatos_vis],
        principio_activo_identificado=pa_identificado,
        alternativas=alternativas,
        explicacion=explicacion,
    )