from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.ml.knn import cargar_modelo as cargar_knn


@asynccontextmanager
async def lifespan(app: FastAPI):
    cargar_knn()
    yield


app = FastAPI(
    title="MediFinder AI Service",
    version="1.0.0",
    description="Sistema de identificación de medicamentos y recomendación de alternativas para Colombia. "
                "Pipeline: OCR → CNN (fallback) → KNN → LLM.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/", tags=["Root"])
async def root():
    return {
        "servicio": "MediFinder",
        "version": "1.0.0",
        "status": "activo",
        "endpoints": [
            "POST /medifinder/analizar   → pipeline completo (imagen → OCR/CNN → KNN → LLM)",
            "POST /medifinder/ocr        → solo extracción de texto",
            "POST /medifinder/alternativas → KNN por principio activo",
            "POST /medifinder/explicar   → explicación LLM de un compuesto",
            "GET  /health",
        ],
    }


@app.get("/health", tags=["Root"])
async def health():
    from app.ml.knn import _modelo
    return {
        "status": "healthy",
        "knn_cargado": _modelo is not None,
    }