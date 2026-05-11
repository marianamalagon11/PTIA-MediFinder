import asyncio
import csv
import json
import re
from pathlib import Path

import httpx
from playwright.async_api import async_playwright
from rapidfuzz import fuzz, process

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────

OUTPUT_DIR    = Path("app/data/raw_images")
MANIFEST_PATH = Path("app/data/scrape_manifest.json")
CSV_MEDS      = Path("app/data/medicamentos_detallado.csv")

DELAY             = 1.0
MAX_POR_CATEGORIA = 60
TIMEOUT_MS        = 60000
DEBUG_HEADLESS    = False

FARMATODO_CATEGORIAS = [
    "https://www.farmatodo.com.co/categorias/salud-y-medicamentos/alivio-del-dolor",
    "https://www.farmatodo.com.co/categorias/salud-y-medicamentos/tratamiento-de-la-gripa",
    "https://www.farmatodo.com.co/categorias/salud-y-medicamentos/salud-digestiva",
    "https://www.farmatodo.com.co/categorias/salud-y-medicamentos/dermatologicos",
]

CRUZVERDE_CATEGORIAS = [
    "https://www.cruzverde.com.co/medicamentos/alivio-del-dolor/",
    "https://www.cruzverde.com.co/medicamentos/gripa-y-tos/",
    "https://www.cruzverde.com.co/medicamentos/salud-digestiva/",
    "https://www.cruzverde.com.co/medicamentos/dermatologicos/",
    "https://www.cruzverde.com.co/medicamentos/sistema-respiratorio/",
]

# Palabras que indican texto promocional (no es nombre de producto)
_PROMOS = ["primera compra", "domicilio", "aprovecha", "prime", "descuento",
           "oferta", "envío", "gratis", "puntos", "app y web", "solo hoy"]


# ─── CSV ──────────────────────────────────────────────────────────────────────

def cargar_mapeo_csv() -> dict[str, str]:
    mapeo = {}
    posibles_col_nombre = ["nombre_comercial", "nombre", "nombre_medicamento", "producto"]
    posibles_col_pa     = ["principio_activo", "principio activo", "PA"]

    def normalizar(texto: str) -> str:
        return re.sub(r"[^a-z0-9 ]", "", texto.lower().strip())

    if not CSV_MEDS.exists():
        print(f"[AVISO] No se encontró {CSV_MEDS}.")
        return mapeo

    with open(CSV_MEDS, encoding="utf-8-sig") as f:
        reader  = csv.DictReader(f)
        cols    = reader.fieldnames or []
        col_nom = next((c for c in posibles_col_nombre if c in cols), None)
        col_pa  = next((c for c in posibles_col_pa if c in cols), None)
        if not col_nom or not col_pa:
            print(f"[AVISO] Columnas disponibles: {cols}")
            return mapeo
        print(f"[CSV] Usando columnas: nombre='{col_nom}' | principio_activo='{col_pa}'")
        for row in reader:
            nombre = normalizar(row[col_nom])
            pa     = normalizar(row[col_pa])
            if nombre and pa:
                mapeo[nombre] = pa

    print(f"[CSV] {len(mapeo)} entradas cargadas")
    return mapeo


def encontrar_principio_activo(nombre_producto: str, mapeo: dict, umbral: int = 70) -> str:
    if not mapeo:
        return "sin_clasificar"
    nombre_norm = re.sub(r"[^a-z0-9 ]", "", nombre_producto.lower().strip())
    resultado   = process.extractOne(nombre_norm, mapeo.keys(), scorer=fuzz.token_set_ratio)
    if resultado and resultado[1] >= umbral:
        return mapeo[resultado[0]]
    return "sin_clasificar"


# ─── DESCARGA ─────────────────────────────────────────────────────────────────

async def descargar_imagen(url: str, destino: Path) -> bool:
    if destino.exists():
        return True
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200 and "image" in resp.headers.get("content-type", ""):
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(resp.content)
                return True
    except Exception as e:
        print(f"  [ERROR descarga] {url}: {e}")
    return False


def nombre_archivo_seguro(texto: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "_", texto.lower().strip())[:80]


def es_promo(texto: str) -> bool:
    txt = texto.lower()
    return any(p in txt for p in _PROMOS) or txt.startswith("%") or "%" in txt[:5]


# ─── EXTRACCIÓN JS (evita context destruction de Angular) ─────────────────────

_JS_FARMATODO = """() => {
    const cards = document.querySelectorAll('[class*="card-ftd"][class*="add-information"]');
    const promos = ["primera compra", "domicilio", "aprovecha", "prime",
                    "descuento", "oferta", "envío", "gratis", "app y web"];
    const resultados = [];

    cards.forEach(card => {
        // Imagen: buscar img real (no SVG, no iconos)
        let imgSrc = '';
        for (const img of card.querySelectorAll('img')) {
            const src = img.src || img.getAttribute('data-src') || img.getAttribute('data-lazy') || '';
            if (src && !src.includes('.svg') && !src.includes('icon') &&
                !src.includes('logo') && src.startsWith('http')) {
                imgSrc = src;
                break;
            }
        }

        // Nombre: texto más largo sin contenido promocional
        let nombre = '';
        let maxLen = 0;
        for (const el of card.querySelectorAll('p, span, h1, h2, h3, h4, a')) {
            const txt = (el.textContent || '').trim();
            const esPromo = promos.some(p => txt.toLowerCase().includes(p)) ||
                            txt.startsWith('%') || /^\\d+%/.test(txt);
            if (!esPromo && txt.length > maxLen && txt.length >= 5 && txt.length < 150) {
                nombre = txt;
                maxLen = txt.length;
            }
        }

        if (imgSrc) {
            resultados.push({ nombre: nombre.trim(), img_src: imgSrc });
        }
    });

    return resultados;
}"""

_JS_CRUZVERDE = """() => {
    // Cruz Verde usa Tailwind sin clases semánticas.
    // Los productos están en un grid: [class*='grid-cols-6'] o [class*='grid-cols-2']
    const grid = document.querySelector('[class*="grid-cols-6"], [class*="grid-cols-4"], [class*="grid-cols-3"]');
    if (!grid) return { error: 'No se encontró grid de productos', cards: [] };

    const promos = ["primera compra", "domicilio", "aprovecha", "descuento",
                    "oferta", "envío", "gratis", "app y web"];
    const resultados = [];

    Array.from(grid.children).forEach(card => {
        // Imagen real del producto
        let imgSrc = '';
        for (const img of card.querySelectorAll('img')) {
            const src = img.src || img.getAttribute('data-src') || '';
            if (src && !src.includes('.svg') && !src.includes('icon') &&
                !src.includes('logo') && src.startsWith('http')) {
                imgSrc = src;
                break;
            }
        }

        // Nombre del producto
        let nombre = '';
        let maxLen = 0;
        for (const el of card.querySelectorAll('p, span, h1, h2, h3, a')) {
            const txt = (el.textContent || '').trim();
            const esPromo = promos.some(p => txt.toLowerCase().includes(p)) ||
                            /^\\d+%/.test(txt);
            if (!esPromo && txt.length > maxLen && txt.length >= 5 && txt.length < 150) {
                nombre = txt;
                maxLen = txt.length;
            }
        }

        if (imgSrc) {
            resultados.push({ nombre: nombre.trim(), img_src: imgSrc });
        }
    });

    return { cards: resultados, total_hijos: grid.children.length };
}"""


# ─── SCRAPER FARMATODO ────────────────────────────────────────────────────────

async def scrapear_farmatodo(page, categoria_url: str, mapeo: dict, manifest: list):
    print(f"\n[FARMATODO] {categoria_url}")
    try:
        await page.goto(categoria_url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
        await page.wait_for_timeout(4000)
    except Exception as e:
        print(f"  [ERROR] No se pudo cargar: {e}")
        return

    productos_descargados = 0

    for intento in range(5):
        # Extraer TODOS los datos de una vez con JS (evita context destruction)
        try:
            datos = await page.evaluate(_JS_FARMATODO)
        except Exception as e:
            print(f"  [ERROR JS] {e}")
            break

        if not datos:
            print(f"  [AVISO] JS no encontró productos (intento {intento + 1}).")
            if intento == 0:
                # Debug: mostrar cuántos card-ftd hay sin el filtro add-information
                total_cards = await page.evaluate(
                    "() => document.querySelectorAll('[class*=\"card-ftd\"]').length"
                )
                print(f"  [DEBUG] Total elementos con 'card-ftd' (sin filtro): {total_cards}")
                imgs_page = await page.evaluate(
                    "() => Array.from(document.querySelectorAll('img')).slice(0,5).map(i => i.src)"
                )
                print(f"  [DEBUG] Primeras 5 imágenes en página: {imgs_page}")
            await page.wait_for_timeout(2000)
            continue

        print(f"  ✔ {len(datos)} productos extraídos vía JS.")

        for item in datos[productos_descargados:]:
            nombre  = item.get("nombre", "").strip()
            img_url = item.get("img_src", "").strip()

            if not img_url:
                continue

            if not nombre:
                nombre = "sin_nombre"

            pa        = encontrar_principio_activo(nombre, mapeo)
            safe_nom  = nombre_archivo_seguro(nombre)
            safe_pa   = nombre_archivo_seguro(pa)
            extension = img_url.split("?")[0].split(".")[-1]
            if extension not in ("jpg", "jpeg", "png", "webp"):
                extension = "jpg"

            destino = OUTPUT_DIR / safe_pa / f"farmatodo_{safe_nom}.{extension}"
            ok = await descargar_imagen(img_url, destino)

            if ok:
                print(f"  ✓ {nombre[:55]} → {pa}")
                manifest.append({
                    "fuente": "farmatodo",
                    "nombre": nombre,
                    "principio_activo": pa,
                    "imagen_path": str(destino),
                    "url_imagen": img_url,
                    "categoria": categoria_url,
                })
                productos_descargados += 1

            await asyncio.sleep(DELAY)

            if productos_descargados >= MAX_POR_CATEGORIA:
                break

        if productos_descargados >= MAX_POR_CATEGORIA:
            break

        # Intentar cargar más productos
        btn = await page.query_selector(
            "[class*='ver-mas'], button[class*='more'], [class*='load-more'], "
            "[class*='siguiente'], [class*='next']"
        )
        if not btn:
            break
        try:
            await btn.scroll_into_view_if_needed()
            await btn.click()
            await page.wait_for_timeout(3000)
        except Exception:
            break

    print(f"  Total descargados: {productos_descargados}")


# ─── SCRAPER CRUZ VERDE ───────────────────────────────────────────────────────

async def scrapear_cruzverde(page, categoria_url: str, mapeo: dict, manifest: list):
    print(f"\n[CRUZ VERDE] {categoria_url}")
    try:
        await page.goto(categoria_url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
        # Angular necesita más tiempo para renderizar el grid de productos
        await page.wait_for_timeout(8000)
    except Exception as e:
        print(f"  [ERROR] No se pudo cargar: {e}")
        return

    productos_descargados = 0

    for intento in range(5):
        try:
            resultado = await page.evaluate(_JS_CRUZVERDE)
        except Exception as e:
            print(f"  [ERROR JS] {e}")
            break

        if "error" in resultado:
            print(f"  [AVISO] {resultado['error']}")
            if intento == 0:
                # Debug: mostrar todas las imágenes disponibles en la página
                imgs = await page.evaluate(
                    "() => Array.from(document.querySelectorAll('img')).slice(0,8).map(i => ({src: i.src, alt: i.alt}))"
                )
                print(f"  [DEBUG] Primeras 8 imágenes en página:")
                for img in imgs:
                    print(f"    src={img['src'][:80]} alt={img['alt']}")
            await page.wait_for_timeout(3000)
            continue

        datos = resultado.get("cards", [])
        print(f"  ✔ Grid encontrado. Hijos: {resultado.get('total_hijos', 0)} | Con imagen: {len(datos)}")

        if not datos:
            await page.wait_for_timeout(2000)
            continue

        for item in datos[productos_descargados:]:
            nombre  = item.get("nombre", "").strip()
            img_url = item.get("img_src", "").strip()

            if not img_url:
                continue

            if not nombre:
                nombre = "sin_nombre"

            pa        = encontrar_principio_activo(nombre, mapeo)
            safe_nom  = nombre_archivo_seguro(nombre)
            safe_pa   = nombre_archivo_seguro(pa)
            extension = img_url.split("?")[0].split(".")[-1]
            if extension not in ("jpg", "jpeg", "png", "webp"):
                extension = "jpg"

            destino = OUTPUT_DIR / safe_pa / f"cruzverde_{safe_nom}.{extension}"
            ok = await descargar_imagen(img_url, destino)

            if ok:
                print(f"  ✓ {nombre[:55]} → {pa}")
                manifest.append({
                    "fuente": "cruzverde",
                    "nombre": nombre,
                    "principio_activo": pa,
                    "imagen_path": str(destino),
                    "url_imagen": img_url,
                    "categoria": categoria_url,
                })
                productos_descargados += 1

            await asyncio.sleep(DELAY)

            if productos_descargados >= MAX_POR_CATEGORIA:
                break

        if productos_descargados >= MAX_POR_CATEGORIA:
            break

        # Scroll para lazy loading + botón ver más
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)
        btn = await page.query_selector(
            "button[class*='load-more'], [class*='loadMore'], [class*='ver-mas'], "
            "button[class*='more'], [class*='siguiente']"
        )
        if not btn:
            break
        try:
            await btn.scroll_into_view_if_needed()
            await btn.click()
            await page.wait_for_timeout(3000)
        except Exception:
            break

    print(f"  Total descargados: {productos_descargados}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    mapeo    = cargar_mapeo_csv()
    manifest = []

    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH) as f:
            manifest = json.load(f)
        print(f"[MANIFEST] {len(manifest)} imágenes ya registradas, continuando...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=DEBUG_HEADLESS)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        await page.route("**/*.{woff,woff2,ttf,eot}", lambda r: r.abort())
        await page.route("**/analytics*", lambda r: r.abort())
        await page.route("**/gtm*", lambda r: r.abort())

        print("\n═══ FARMATODO ═══")
        for url in FARMATODO_CATEGORIAS:
            await scrapear_farmatodo(page, url, mapeo, manifest)

        print("\n═══ CRUZ VERDE ═══")
        for url in CRUZVERDE_CATEGORIAS:
            await scrapear_cruzverde(page, url, mapeo, manifest)

        await browser.close()

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\nScraping finalizado.")
    print(f"   Imágenes totales: {len(manifest)}")
    print(f"   Guardadas en:     {OUTPUT_DIR}")

    resumen: dict[str, int] = {}
    for item in manifest:
        resumen[item["principio_activo"]] = resumen.get(item["principio_activo"], 0) + 1
    print("\n Imágenes por principio activo:")
    for pa, count in sorted(resumen.items(), key=lambda x: -x[1])[:20]:
        print(f"   {pa:<40} {count} imgs")


if __name__ == "__main__":
    asyncio.run(main())