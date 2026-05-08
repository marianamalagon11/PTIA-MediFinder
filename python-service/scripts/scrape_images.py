import asyncio
import csv
import json
import os
import re
from pathlib import Path

import httpx
from playwright.async_api import async_playwright
from rapidfuzz import fuzz, process

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────

OUTPUT_DIR    = Path("app/data/raw_images")
MANIFEST_PATH = Path("app/data/scrape_manifest.json")
CSV_MEDS      = Path("app/data/medicamentos_detallado.csv")

DELAY             = 1.5
MAX_POR_CATEGORIA = 60
TIMEOUT_MS        = 60000
DEBUG_HEADLESS    = False  # False = navegador visible para depurar

FARMATODO_CATEGORIAS = [
    "https://www.farmatodo.com.co/categorias/salud-y-medicamentos/tratamiento-de-la-gripa",
    "https://www.farmatodo.com.co/categorias/salud-y-medicamentos/alivio-del-dolor",
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

# ─── SELECTORES ───────────────────────────────────────────────────────────────
# Farmatodo: confirmados por debug — usa clases propias (no VTEX)
FARMATODO_SEL = {
    "card":    "[class*='card-ftd'][class*='add-information']",
    "nombre":  "[class*='name'], [class*='title'], p[class*='description'], a[class*='product']",
    "imagen":  "[class*='picture-wrapper'] img, [class*='product-image'] img, img[class*='image']",
    "ver_mas": "[class*='ver-mas'], button[class*='more'], [class*='load-more'], [class*='siguiente']",
}

# Cruz Verde: Angular + Tailwind — actualizar tras inspección con debug_card
CRUZVERDE_SEL = {
    "card":    "[class*='product-card'], [class*='productCard'], app-product-card, "
               "[class*='product-item'], [class*='item-product']",
    "nombre":  "[class*='product-name'], [class*='productName'], [class*='name'], "
               "h2, h3, p[class*='title'], span[class*='name']",
    "imagen":  "img[class*='product'], [class*='product-image'] img, "
               "[class*='img-product'] img, figure img, img",
    "ver_mas": "button[class*='load-more'], [class*='loadMore'], [class*='ver-mas'], "
               "button[class*='more'], [class*='siguiente']",
}


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
            print(f"[AVISO] Columnas: {cols}")
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


# ─── DEBUG ────────────────────────────────────────────────────────────────────

async def debug_clases_pagina(page, sitio: str):
    print(f"\n  [DEBUG {sitio}] Clases con palabras clave de producto:")
    try:
        clases = await page.evaluate("""() => {
            const kw = ['product', 'card', 'item', 'shelf', 'catalog', 'ftd'];
            const encontrados = new Set();
            document.querySelectorAll('*[class]').forEach(el => {
                const cls = (el.className || '').toString();
                if (kw.some(k => cls.toLowerCase().includes(k)))
                    encontrados.add(cls.split(' ').slice(0,4).join(' '));
            });
            return Array.from(encontrados).slice(0, 20);
        }""")
        for c in clases:
            print(f"    → {c}")
    except Exception as e:
        print(f"  [DEBUG] Error: {e}")


async def debug_primera_card(page, selector_card: str, sitio: str):
    """Inspecciona la primera tarjeta encontrada para ver su HTML interno."""
    print(f"\n  [DEBUG {sitio}] Inspeccionando primera card con selector '{selector_card}':")
    try:
        cards = await page.query_selector_all(selector_card)
        if not cards:
            print("  [DEBUG] Ninguna card encontrada con ese selector.")
            return
        print(f"  [DEBUG] {len(cards)} cards encontradas.")
        html = await cards[0].inner_html()
        # Mostrar solo las primeras 800 chars para no saturar el log
        print(f"  [DEBUG] HTML de la primera card (primeros 800 chars):")
        print(f"  {html[:800]}")
    except Exception as e:
        print(f"  [DEBUG] Error: {e}")


# ─── SCRAPER FARMATODO ────────────────────────────────────────────────────────

async def scrapear_farmatodo(page, categoria_url: str, mapeo: dict, manifest: list):
    print(f"\n[FARMATODO] {categoria_url}")
    try:
        await page.goto(categoria_url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
        await page.wait_for_timeout(4000)
    except Exception as e:
        print(f"  [ERROR] No se pudo cargar: {e}")
        return

    productos_encontrados = 0

    for intento in range(5):
        cards = await page.query_selector_all(FARMATODO_SEL["card"])

        if not cards:
            if intento == 0:
                await debug_clases_pagina(page, "FARMATODO")
            print("  [AVISO] No se encontraron tarjetas. Revisá FARMATODO_SEL['card'].")
            break

        if intento == 0:
            print(f"  ✔ {len(cards)} tarjetas encontradas con selector card.")
            # Debug: ver qué hay dentro de la primera card para ajustar nombre/imagen
            await debug_primera_card(page, FARMATODO_SEL["card"], "FARMATODO")

        for card in cards[productos_encontrados:MAX_POR_CATEGORIA]:
            try:
                el_nombre = await card.query_selector(FARMATODO_SEL["nombre"])
                el_imagen = await card.query_selector(FARMATODO_SEL["imagen"])

                if not el_nombre or not el_imagen:
                    continue

                nombre  = (await el_nombre.inner_text()).strip()
                img_url = (
                    await el_imagen.get_attribute("src") or
                    await el_imagen.get_attribute("data-src") or
                    await el_imagen.get_attribute("data-lazy")
                )

                if not img_url or not nombre:
                    continue

                if img_url.startswith("//"):
                    img_url = "https:" + img_url

                pa        = encontrar_principio_activo(nombre, mapeo)
                safe_nom  = nombre_archivo_seguro(nombre)
                safe_pa   = nombre_archivo_seguro(pa)
                extension = img_url.split("?")[0].split(".")[-1]
                if extension not in ("jpg", "jpeg", "png", "webp"):
                    extension = "jpg"

                destino = OUTPUT_DIR / safe_pa / f"farmatodo_{safe_nom}.{extension}"
                ok = await descargar_imagen(img_url, destino)

                if ok:
                    print(f"  ✓ {nombre[:50]} → {pa}")
                    manifest.append({
                        "fuente": "farmatodo",
                        "nombre": nombre,
                        "principio_activo": pa,
                        "imagen_path": str(destino),
                        "url_imagen": img_url,
                        "categoria": categoria_url,
                    })
                    productos_encontrados += 1

                await asyncio.sleep(DELAY)

            except Exception as e:
                print(f"  [ERROR card] {e}")
                continue

            if productos_encontrados >= MAX_POR_CATEGORIA:
                break

        if productos_encontrados >= MAX_POR_CATEGORIA:
            break

        btn = await page.query_selector(FARMATODO_SEL["ver_mas"])
        if not btn:
            break
        try:
            await btn.click()
            await page.wait_for_timeout(2500)
        except Exception:
            break

    print(f"  Total descargados: {productos_encontrados}")


# ─── SCRAPER CRUZ VERDE ───────────────────────────────────────────────────────

async def scrapear_cruzverde(page, categoria_url: str, mapeo: dict, manifest: list):
    print(f"\n[CRUZ VERDE] {categoria_url}")
    try:
        await page.goto(categoria_url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
        # Cruz Verde es Angular → esperar más tiempo para que renderice
        await page.wait_for_timeout(5000)
    except Exception as e:
        print(f"  [ERROR] No se pudo cargar: {e}")
        return

    productos_encontrados = 0

    for intento in range(5):
        cards = await page.query_selector_all(CRUZVERDE_SEL["card"])

        if not cards:
            if intento == 0:
                await debug_clases_pagina(page, "CRUZ VERDE")
                print("  [AVISO] No se encontraron tarjetas. Revisá CRUZVERDE_SEL['card'].")
            break

        if intento == 0:
            print(f"  ✔ {len(cards)} tarjetas encontradas.")
            await debug_primera_card(page, CRUZVERDE_SEL["card"], "CRUZ VERDE")

        for card in cards[productos_encontrados:MAX_POR_CATEGORIA]:
            try:
                el_nombre = await card.query_selector(CRUZVERDE_SEL["nombre"])
                el_imagen = await card.query_selector(CRUZVERDE_SEL["imagen"])

                if not el_nombre or not el_imagen:
                    continue

                nombre  = (await el_nombre.inner_text()).strip()
                img_url = (
                    await el_imagen.get_attribute("src") or
                    await el_imagen.get_attribute("data-src") or
                    await el_imagen.get_attribute("data-lazy-src")
                )

                if not img_url or not nombre:
                    continue

                if img_url.startswith("//"):
                    img_url = "https:" + img_url

                pa        = encontrar_principio_activo(nombre, mapeo)
                safe_nom  = nombre_archivo_seguro(nombre)
                safe_pa   = nombre_archivo_seguro(pa)
                extension = img_url.split("?")[0].split(".")[-1]
                if extension not in ("jpg", "jpeg", "png", "webp"):
                    extension = "jpg"

                destino = OUTPUT_DIR / safe_pa / f"cruzverde_{safe_nom}.{extension}"
                ok = await descargar_imagen(img_url, destino)

                if ok:
                    print(f"  ✓ {nombre[:50]} → {pa}")
                    manifest.append({
                        "fuente": "cruzverde",
                        "nombre": nombre,
                        "principio_activo": pa,
                        "imagen_path": str(destino),
                        "url_imagen": img_url,
                        "categoria": categoria_url,
                    })
                    productos_encontrados += 1

                await asyncio.sleep(DELAY)

            except Exception as e:
                print(f"  [ERROR card] {e}")
                continue

            if productos_encontrados >= MAX_POR_CATEGORIA:
                break

        if productos_encontrados >= MAX_POR_CATEGORIA:
            break

        btn = await page.query_selector(CRUZVERDE_SEL["ver_mas"])
        if not btn:
            break
        try:
            await btn.scroll_into_view_if_needed()
            await btn.click()
            await page.wait_for_timeout(3000)
        except Exception:
            break

    print(f"  Total descargados: {productos_encontrados}")


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