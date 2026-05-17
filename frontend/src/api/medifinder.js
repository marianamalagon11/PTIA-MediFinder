const API_BASE = '/medifinder';

export async function realizarOCR(file) {
  const form = new FormData();
  form.append('imagen', file);
  const res = await fetch(`${API_BASE}/ocr`, { method: 'POST', body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Error al procesar la imagen');
  }
  return res.json();
}

export async function buscarAlternativas(principioActivo, concentracion = '', formaFarmaceutica = '', k = 5) {
  const form = new FormData();
  form.append('principio_activo', principioActivo);
  form.append('concentracion', concentracion);
  form.append('forma_farmaceutica', formaFarmaceutica);
  form.append('k', String(k));
  const res = await fetch(`${API_BASE}/alternativas`, { method: 'POST', body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Error al buscar alternativas');
  }
  return res.json();
}

export async function explicarCompuesto(principioActivo) {
  const form = new FormData();
  form.append('principio_activo', principioActivo);
  const res = await fetch(`${API_BASE}/explicar`, { method: 'POST', body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Error al generar explicación');
  }
  return res.json();
}
