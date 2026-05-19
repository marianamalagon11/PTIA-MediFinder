# MediFinder 💊

**Identificación inteligente de medicamentos colombianos mediante IA** — OCR · CNN · KNN · LLM

MediFinder es una aplicación web que permite a pacientes colombianos fotografiar el empaque de un medicamento, identificar su principio activo y encontrar alternativas equivalentes registradas en el INVIMA, con una explicación generada por IA en lenguaje claro.

---

## ¿Qué problema resuelve?

Durante la crisis de desabastecimiento de medicamentos en Colombia, muchos pacientes no pueden conseguir el medicamento prescrito y no saben qué alternativa pedir porque desconocen el principio activo. El INVIMA registra más de 153.000 medicamentos, pero no existe una herramienta accesible que conecte nombre comercial → principio activo → alternativas disponibles.

MediFinder resuelve esto en tres pasos: **foto → identificación → alternativas**.

---

## Demo del flujo

[🎬 Video Funcional]([https://ejemplo.com](https://youtu.be/m80PA7jCPk4))

```
📷 Usuario fotografía el empaque
        ↓
🔍 OCR extrae el texto (Tesseract, múltiples estrategias)
        ↓
📋 Verificación humana de los campos extraídos
        ↓
🤖 KNN busca alternativas por principio activo (153k medicamentos INVIMA)
        ↓
💬 LLM explica el principio activo al paciente (Claude Haiku + RAG)
```

---

## Arquitectura

```
frontend/                         # React + Vite
└── src/
    ├── pages/
    │   ├── Home.jsx              # Captura / subida de imagen
    │   ├── Verification.jsx      # Verificación de campos OCR
    │   └── Results.jsx           # Alternativas + explicación LLM
    └── api/
        └── medifinder.js         # Cliente API

python-service/                   # FastAPI
├── app/
│   ├── api/routes.py             # Endpoints del pipeline
│   ├── ml/
│   │   ├── ocr.py                # Tesseract + preprocesamiento
│   │   ├── cnn.py                # EfficientNet-B0 + ChromaDB
│   │   ├── knn.py                # NearestNeighbors sklearn
│   │   └── llm.py                # Claude Haiku + RAG
│   └── data/
│       ├── medicamentos_invima.csv      # 153.523 registros
│       ├── medicamentos_detallado.csv
│       ├── principios_activos.csv
│       ├── raw_images/           # Imágenes scrapeadas
│       └── embeddings_db/        # ChromaDB
└── scripts/
    ├── scrape_images.py          # Playwright — Farmatodo, Cruz Verde
    ├── train_knn.py              # Entrena modelo KNN
    ├── build_embeddings.py       # Genera embeddings CNN
    └── build_knowledge_base.py   # Base RAG para LLM

models/
└── medifinder/
    ├── knn_model.pkl
    └── knn_metadata.pkl
```

---

## Stack tecnológico

| Capa              | Tecnología                                                                  |
|-------------------|-----------------------------------------------------------------------------|
| Frontend          | React 18, React Router v6, Vite                                             |
| Backend           | FastAPI, Uvicorn, Pydantic                                                  |
| OCR               | Tesseract 5, OpenCV, Pillow                                                 |
| CNN               | EfficientNet-B0 (PyTorch / torchvision)                                     |
| Vector DB         | ChromaDB                                                                    |
| Embeddings texto  | SentenceTransformer `paraphrase-multilingual-MiniLM-L12-v2`                 |
| KNN               | scikit-learn `NearestNeighbors`                                             |
| LLM               | Claude Haiku (Anthropic API)                                                |
| Scraping          | Playwright, httpx                                                           |
| Datos             | CSV INVIMA — 153.523 medicamentos colombianos                               |

---

## Instalación y ejecución local

### Prerrequisitos

- Python 3.11+
- Node.js 18+
- Tesseract OCR instalado en el sistema:
  - **Windows:** [Descargar instalador UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) — marcar idioma **Spanish** durante la instalación
  - **Linux/Docker:** `apt-get install tesseract-ocr tesseract-ocr-spa`

### Backend

```bash
cd python-service

# Crear y activar entorno virtual
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/Mac

# Instalar dependencias
pip install -r requirements.txt

# Crear archivo de variables de entorno
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# Iniciar servidor
python -m uvicorn app.main:app --host 0.0.0.0 --port 8002
```

El backend queda disponible en `http://localhost:8002`.  
Documentación interactiva (Swagger): `http://localhost:8002/docs`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Docker (solo backend)

```bash
cd python-service
docker build -t medifinder-api .
docker run -p 8002:8002 --env ANTHROPIC_API_KEY=sk-ant-... medifinder-api
```

---

## Pipeline de IA

### 1. OCR — Extracción de texto

- Escala la imagen a 2× para mejorar la precisión de Tesseract.
- Evalúa las 4 orientaciones cardinales (0°, 90°, 180°, 270°) y selecciona la de mayor confianza — más robusto que OSD para empaques con texto en múltiples direcciones.
- Prueba múltiples estrategias de preprocesamiento: umbral Otsu, CLAHE adaptativo, canales de color (R, R−B) para texto en empaques de colores vivos.
- Combina 4 modos PSM de Tesseract (3, 4, 6, 11) y retorna el resultado de mayor confianza.

### 2. Mapeo al catálogo INVIMA

Búsqueda en cascada en `buscar_pa_por_nombre`:

1. Cada palabra del texto OCR se intenta como principio activo directo en el catálogo.
2. Coincidencia exacta de nombre comercial normalizado.
3. Búsqueda por la palabra más larga y significativa (con filtro de stopwords farmacéuticas).
4. Fuzzy matching con `rapidfuzz` como último recurso.

### 3. CNN — Fallback visual

Si el OCR no produce coincidencia válida en el catálogo, EfficientNet-B0 extrae un vector de 1.280 dimensiones de la imagen y consulta ChromaDB para encontrar el medicamento visualmente más similar entre las imágenes de referencia indexadas.

### 4. KNN — Alternativas

`NearestNeighbors` de scikit-learn busca los *k* medicamentos más cercanos en el espacio de características farmacológicas (principio activo, concentración, forma farmacéutica, clase terapéutica, vía de administración). Incluye deduplicación en dos capas para evitar mostrar el mismo producto registrado con diferentes nombres en el INVIMA.

### 5. LLM — Explicación

Claude Haiku genera una explicación estructurada del principio activo en seis secciones (qué es, mecanismo de acción, efectos secundarios, contraindicaciones, interacciones, recomendaciones), usando RAG sobre una base de conocimiento de 11.217 documentos construida a partir del catálogo INVIMA y Wikipedia.

---

## Endpoints de la API

| Método | Ruta                       | Descripción                                           |
|--------|----------------------------|-------------------------------------------------------|
| GET    | `/health`                  | Estado del servicio y carga del modelo KNN            |
| POST   | `/medifinder/ocr`          | Extrae texto de la imagen del empaque                 |
| POST   | `/medifinder/analizar`     | Pipeline completo: imagen → PA → alternativas → explicación |
| POST   | `/medifinder/alternativas` | Busca alternativas dado un principio activo           |
| POST   | `/medifinder/explicar`     | Genera explicación LLM de un principio activo         |

---

## Scripts de entrenamiento y datos

```bash
# Entrenar modelo KNN sobre el catálogo INVIMA
python train.py --knn

# Scrapear imágenes de Farmatodo y Cruz Verde
python scripts/scrape_images.py

# Construir base de embeddings visuales (CNN)
python scripts/build_embeddings.py

# Construir knowledge base para RAG (LLM)
python scripts/build_knowledge_base.py
```

---

## Variables de entorno

Crear un archivo `.env` dentro de `python-service/`:

```env
ANTHROPIC_API_KEY=sk-ant-...
```

Configuración adicional en `app/config/settings.py`:

| Variable                   | Default | Descripción                                      |
|----------------------------|---------|--------------------------------------------------|
| `knn_k`                    | `5`     | Número de alternativas a retornar                |
| `ocr_confidence_threshold` | `60`    | Confianza mínima OCR para usar resultado         |
| `cnn_similarity_threshold` | `0.45`  | Similitud mínima para candidatos visuales        |

---

## Limitaciones conocidas

- **Ángulos oblicuos:** imágenes tomadas con la caja inclinada o sostenida con la mano reducen significativamente la precisión del OCR.
- **Blísteres metálicos:** las reflexiones especulares en láminas de aluminio destruyen la información de texto antes de que cualquier preprocesamiento pueda actuar.
- **Cobertura CNN:** el modelo visual solo reconoce medicamentos cuyas imágenes de referencia fueron indexadas durante el scraping (225 imágenes de Farmatodo y Cruz Verde).
- **RAG LLM:** si el principio activo no está bien representado en la knowledge base, el LLM puede recuperar contexto incorrecto. Se recomienda verificar siempre la información con un profesional de salud.

---

## Datos

Los archivos CSV del catálogo INVIMA no se incluyen en el repositorio por su tamaño. Deben ubicarse en:

```
python-service/app/data/
├── medicamentos_invima.csv         # ~153.523 registros
├── medicamentos_detallado.csv      # ~26.415 registros
└── principios_activos.csv          # ~11.475 registros
```

---

## ⚠️ Aviso médico

> MediFinder es una herramienta informativa de apoyo. La información presentada **no reemplaza** la asesoría de un médico o farmacéutico. Siempre consulte con un profesional de la salud antes de cambiar o sustituir cualquier medicamento.

---

## Contexto académico

Proyecto desarrollado para la asignatura **Proyecto de Tecnologías de Inteligencia Artificial (PTIA)** — Escuela Colombiana de Ingeniería Julio Garavito, Departamento de Ingeniería de Sistemas.
