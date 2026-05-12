import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import Header from '../components/Header';
import LoadingOverlay from '../components/LoadingOverlay';
import { buscarAlternativas, explicarCompuesto } from '../api/medifinder';

const EditIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
    <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
  </svg>
);

const ImageIcon = () => (
  <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
    <circle cx="8.5" cy="8.5" r="1.5"/>
    <polyline points="21 15 16 10 5 21"/>
  </svg>
);

const CheckIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20 6 9 17 4 12"/>
  </svg>
);

function FieldRow({ label, value, onChange, placeholder = '' }) {
  const [editing, setEditing] = useState(false);

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '14px 0',
      borderBottom: '1px solid #F3F4F6',
      gap: 12,
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ fontSize: 13, fontWeight: 500, color: '#4A5565', marginBottom: 4 }}>{label}</p>
        {editing ? (
          <input
            className="field-input"
            value={value}
            onChange={e => onChange(e.target.value)}
            onBlur={() => setEditing(false)}
            onKeyDown={e => { if (e.key === 'Enter') setEditing(false); }}
            placeholder={placeholder}
            autoFocus
            style={{ marginTop: 2 }}
          />
        ) : (
          <p style={{
            fontSize: 16,
            color: value ? '#1E2939' : '#99A1AF',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}>
            {value || placeholder}
          </p>
        )}
      </div>
      <button
        onClick={() => setEditing(e => !e)}
        style={{
          flexShrink: 0,
          width: 36,
          height: 36,
          borderRadius: 8,
          border: '1.5px solid #E5E7EB',
          background: '#FFFFFF',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#6A7282',
          transition: 'background 0.15s',
        }}
        onMouseEnter={e => e.currentTarget.style.background = '#F9FAFB'}
        onMouseLeave={e => e.currentTarget.style.background = '#FFFFFF'}
        aria-label={`Editar ${label}`}
      >
        <EditIcon />
      </button>
    </div>
  );
}

export default function Verification() {
  const { state } = useLocation();
  const navigate = useNavigate();

  const { imagenUrl, ocrResult, prefilledFields } = state || {};

  const [fields, setFields] = useState({
    nombreComercial: prefilledFields?.nombreComercial || '',
    principioActivo: prefilledFields?.principioActivo || '',
    concentracion:   prefilledFields?.concentracion   || '',
    formaFarmaceutica: prefilledFields?.formaFarmaceutica || '',
    registroInvima:  prefilledFields?.registroInvima  || '',
  });

  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState('');

  function setField(key) {
    return (val) => setFields(f => ({ ...f, [key]: val }));
  }

  async function confirmar() {
    if (!fields.principioActivo.trim()) {
      setError('Por favor ingresa el principio activo del medicamento.');
      return;
    }
    setError('');
    setLoading(true);
    try {
      const [alternativas, explicacion] = await Promise.all([
        buscarAlternativas(fields.principioActivo, fields.concentracion, fields.formaFarmaceutica),
        explicarCompuesto(fields.principioActivo),
      ]);
      navigate('/resultados', {
        state: { imagenUrl, fields, alternativas, explicacion, ocrResult },
      });
    } catch (e) {
      setError(e.message || 'Error al consultar el servidor.');
    } finally {
      setLoading(false);
    }
  }

  if (!state) {
    navigate('/');
    return null;
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: 'linear-gradient(180deg, #EFF6FF 0%, #FFFFFF 50%, #F0FDF4 100%)',
      display: 'flex',
      flexDirection: 'column',
    }}>
      {loading && <LoadingOverlay message="Buscando alternativas y generando explicación..." />}
      <Header showBack />

      <main style={{ flex: 1, display: 'flex', justifyContent: 'center', padding: '40px 32px' }}>
        <div style={{ maxWidth: 768, width: '100%', display: 'flex', flexDirection: 'column', gap: 28 }}>

          {/* Section heading */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <h1 style={{ fontSize: 24, fontWeight: 500, color: '#1E2939' }}>
              Verifica el medicamento
            </h1>
            <p style={{ fontSize: 18, color: '#4A5565' }}>
              Revisa que la información extraída sea correcta
            </p>
            {ocrResult && (
              <div style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                background: ocrResult.ocr_exitoso ? '#DCFCE7' : '#FFFBEB',
                color: ocrResult.ocr_exitoso ? '#008236' : '#7B3306',
                padding: '4px 12px',
                borderRadius: 20,
                fontSize: 13,
                fontWeight: 500,
                width: 'fit-content',
              }}>
                {ocrResult.ocr_exitoso ? '✓' : '⚠️'}&nbsp;
                {ocrResult.ocr_exitoso
                  ? `OCR exitoso — confianza ${ocrResult.confianza}%`
                  : `Confianza baja (${ocrResult.confianza}%) — revisa los campos`}
              </div>
            )}
          </div>

          {/* Main panel */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: 20,
            background: '#FFFFFF',
            borderRadius: 16,
            boxShadow: '0 1px 4px rgba(0,0,0,0.08), 0 4px 16px rgba(0,0,0,0.06)',
            overflow: 'hidden',
          }}>
            {/* Image preview */}
            <div style={{
              background: 'linear-gradient(135deg, #F3F4F6 0%, #F9FAFB 100%)',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 12,
              padding: 32,
              minHeight: 400,
            }}>
              {imagenUrl ? (
                <img
                  src={imagenUrl}
                  alt="Imagen capturada"
                  style={{
                    maxWidth: '100%',
                    maxHeight: 280,
                    objectFit: 'contain',
                    borderRadius: 12,
                    boxShadow: '0 2px 8px rgba(0,0,0,0.12)',
                  }}
                />
              ) : (
                <>
                  <ImageIcon />
                  <p style={{ fontSize: 16, color: '#6A7282' }}>Imagen capturada</p>
                </>
              )}
            </div>

            {/* Editable fields */}
            <div style={{ padding: '24px 28px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
              <FieldRow
                label="Nombre comercial"
                value={fields.nombreComercial}
                onChange={setField('nombreComercial')}
                placeholder="Ej: Ibuprofeno Genfar"
              />
              <FieldRow
                label="Principio activo *"
                value={fields.principioActivo}
                onChange={setField('principioActivo')}
                placeholder="Ej: Ibuprofeno"
              />
              <FieldRow
                label="Concentración"
                value={fields.concentracion}
                onChange={setField('concentracion')}
                placeholder="Ej: 400 mg"
              />
              <FieldRow
                label="Forma farmacéutica"
                value={fields.formaFarmaceutica}
                onChange={setField('formaFarmaceutica')}
                placeholder="Ej: Tableta"
              />
              <FieldRow
                label="Registro INVIMA"
                value={fields.registroInvima}
                onChange={setField('registroInvima')}
                placeholder="Ej: 2020M-0012345-R1"
              />
            </div>
          </div>

          {/* Error */}
          {error && (
            <div className="error-banner">
              <span>⚠️</span>
              {error}
            </div>
          )}

          {/* CTA */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'center' }}>
            <button
              className="btn btn-green"
              onClick={confirmar}
              disabled={loading}
              style={{ width: 280, height: 64, fontSize: 16 }}
            >
              <CheckIcon />
              Confirmar datos
            </button>
            <p style={{ fontSize: 14, color: '#6A7282', textAlign: 'center' }}>
              Asegúrate de que la información sea correcta antes de continuar
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}
