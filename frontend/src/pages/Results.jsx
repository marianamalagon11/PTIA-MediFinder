import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import Header from '../components/Header';

const AlertIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
    <line x1="12" y1="9" x2="12" y2="13"/>
    <line x1="12" y1="17" x2="12.01" y2="17"/>
  </svg>
);

const SearchIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
  </svg>
);

const ChevronDown = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="6 9 12 15 18 9"/>
  </svg>
);

const ChevronUp = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="18 15 12 9 6 15"/>
  </svg>
);

function badgeProps(tipo, nivel) {
  if (nivel === 1 || tipo === 'equivalente') {
    return { label: 'Mismo principio activo', bg: '#DCFCE7', color: '#008236' };
  }
  return { label: 'Alternativa terapéutica', bg: '#DBEAFE', color: '#1447E6' };
}

function AlternativaCard({ alt, index }) {
  const badge = badgeProps(alt.tipo, alt.nivel);
  return (
    <div style={{
      background: '#FFFFFF',
      borderRadius: 16,
      boxShadow: '0 1px 4px rgba(0,0,0,0.08), 0 4px 16px rgba(0,0,0,0.06)',
      padding: 24,
      display: 'flex',
      flexDirection: 'column',
      gap: 14,
    }}>
      {/* Top row: badge + level indicator */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <span className="badge" style={{ background: badge.bg, color: badge.color }}>
          {badge.label}
        </span>
        <span style={{
          background: 'linear-gradient(135deg, #2B7FFF 0%, #05DF72 100%)',
          color: '#FFFFFF',
          padding: '4px 12px',
          borderRadius: 20,
          fontSize: 12,
          fontWeight: 500,
        }}>
          #{index + 1} recomendado
        </span>
      </div>

      {/* Medicine name */}
      <div>
        <p style={{ fontSize: 17, fontWeight: 600, color: '#1E2939', lineHeight: 1.3 }}>
          {alt.nombre || '—'}
        </p>
        {alt.clase_terapeutica && (
          <p style={{ fontSize: 13, color: '#6A7282', marginTop: 2 }}>{alt.clase_terapeutica}</p>
        )}
      </div>

      {/* Details grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px' }}>
        {[
          ['Principio activo', alt.principio_activo],
          ['Concentración',    alt.concentracion],
          ['Forma',            alt.forma_farmaceutica],
          ['Titular',          alt.titular || alt.laboratorio],
        ].map(([label, value]) =>
          value ? (
            <div key={label}>
              <p style={{ fontSize: 12, color: '#6A7282', fontWeight: 500 }}>{label}</p>
              <p style={{ fontSize: 14, color: '#1E2939', marginTop: 2 }}>{value}</p>
            </div>
          ) : null
        )}
      </div>
    </div>
  );
}

function ExplicacionSection({ explicacion }) {
  const [expanded, setExpanded] = useState(false);

  if (!explicacion) return null;

  const preview = explicacion.explicacion?.slice(0, 200) + '...';

  return (
    <div style={{
      background: '#FFFFFF',
      borderRadius: 16,
      boxShadow: '0 1px 4px rgba(0,0,0,0.08), 0 4px 16px rgba(0,0,0,0.06)',
      overflow: 'hidden',
    }}>
      <button
        onClick={() => setExpanded(e => !e)}
        style={{
          width: '100%',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          padding: '20px 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          textAlign: 'left',
          fontFamily: 'inherit',
        }}
      >
        <div>
          <p style={{ fontSize: 18, fontWeight: 500, color: '#1E2939' }}>
            Información del principio activo
          </p>
          <p style={{ fontSize: 14, color: '#6A7282', marginTop: 4 }}>
            {explicacion.principio_activo} · {explicacion.fuente_kb ? 'Base de conocimiento' : 'Modelo de lenguaje'}
          </p>
        </div>
        {expanded ? <ChevronUp /> : <ChevronDown />}
      </button>

      {expanded && (
        <div style={{ padding: '0 24px 24px', borderTop: '1px solid #F3F4F6' }}>
          <div style={{
            marginTop: 16,
            fontSize: 15,
            color: '#374151',
            lineHeight: 1.75,
            whiteSpace: 'pre-wrap',
          }}>
            {explicacion.explicacion}
          </div>
        </div>
      )}

      {!expanded && (
        <div style={{
          padding: '0 24px 20px',
          fontSize: 14,
          color: '#6A7282',
          lineHeight: 1.6,
          borderTop: '1px solid #F3F4F6',
          paddingTop: 16,
        }}>
          {preview}
          <button
            onClick={() => setExpanded(true)}
            style={{
              marginLeft: 4,
              background: 'none',
              border: 'none',
              color: '#2B7FFF',
              cursor: 'pointer',
              fontFamily: 'inherit',
              fontSize: 14,
              fontWeight: 500,
              padding: 0,
            }}
          >
            Ver más
          </button>
        </div>
      )}
    </div>
  );
}

export default function Results() {
  const { state } = useLocation();
  const navigate = useNavigate();

  const { fields, alternativas = [], explicacion, imagenUrl } = state || {};

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
      <Header showBack />

      <main style={{ flex: 1, display: 'flex', justifyContent: 'center', padding: '40px 32px' }}>
        <div style={{ maxWidth: 1152, width: '100%', display: 'flex', flexDirection: 'column', gap: 28 }}>

          {/* Title */}
          <h1 style={{ fontSize: 24, fontWeight: 500, color: '#1E2939' }}>Resultados</h1>

          {/* Warning banner */}
          <div style={{
            background: '#FFFBEB',
            borderRadius: 12,
            padding: '16px 20px',
            display: 'flex',
            alignItems: 'flex-start',
            gap: 12,
          }}>
            <span style={{ color: '#D97706', flexShrink: 0, marginTop: 1 }}><AlertIcon /></span>
            <p style={{ fontSize: 15, fontWeight: 700, color: '#7B3306', lineHeight: 1.5 }}>
              Aviso importante: Esta información no reemplaza la asesoría de un médico o farmacéutico. Consulta siempre a un profesional de la salud antes de cambiar tu medicación.
            </p>
          </div>

          {/* Identified medication card */}
          <div style={{
            background: 'linear-gradient(135deg, #2B7FFF 0%, #155DFC 100%)',
            borderRadius: 16,
            padding: '28px 32px',
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
          }}>
            <p style={{ fontSize: 14, color: '#BFDBFE', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Medicamento identificado
            </p>
            <p style={{ fontSize: 22, fontWeight: 600, color: '#FFFFFF' }}>
              {fields?.nombreComercial || fields?.principioActivo || '—'}
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 24px', marginTop: 4 }}>
              {fields?.principioActivo && (
                <p style={{ fontSize: 15, color: '#EFF6FF' }}>
                  Principio activo: <strong>{fields.principioActivo}</strong>
                </p>
              )}
              {fields?.concentracion && (
                <p style={{ fontSize: 15, color: '#EFF6FF' }}>
                  Concentración: <strong>{fields.concentracion}</strong>
                </p>
              )}
              {fields?.formaFarmaceutica && (
                <p style={{ fontSize: 15, color: '#EFF6FF' }}>
                  Forma: <strong>{fields.formaFarmaceutica}</strong>
                </p>
              )}
            </div>
          </div>

          {/* LLM explanation (expandable) */}
          {explicacion && <ExplicacionSection explicacion={explicacion} />}

          {/* Alternatives */}
          <div>
            <h2 style={{ fontSize: 20, fontWeight: 500, color: '#1E2939', marginBottom: 16 }}>
              Alternativas encontradas
              {alternativas.length > 0 && (
                <span style={{
                  marginLeft: 10,
                  background: '#EFF6FF',
                  color: '#2B7FFF',
                  padding: '2px 10px',
                  borderRadius: 20,
                  fontSize: 14,
                  fontWeight: 500,
                }}>
                  {alternativas.length}
                </span>
              )}
            </h2>

            {alternativas.length === 0 ? (
              <div style={{
                background: '#FFFFFF',
                borderRadius: 16,
                padding: '40px 32px',
                textAlign: 'center',
                boxShadow: '0 1px 4px rgba(0,0,0,0.08)',
              }}>
                <p style={{ fontSize: 18, color: '#6A7282' }}>No se encontraron alternativas en el catálogo.</p>
                <p style={{ fontSize: 14, color: '#99A1AF', marginTop: 8 }}>
                  Verifica que el principio activo esté escrito correctamente.
                </p>
              </div>
            ) : (
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
                gap: 20,
              }}>
                {alternativas.map((alt, i) => (
                  <AlternativaCard key={i} alt={alt} index={i} />
                ))}
              </div>
            )}
          </div>

          {/* Bottom CTA */}
          <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 8, paddingBottom: 24 }}>
            <button
              className="btn btn-score"
              onClick={() => navigate('/')}
              style={{ height: 64, paddingInline: 36, fontSize: 16, boxShadow: '0 2px 12px rgba(43,127,255,0.25)' }}
            >
              <SearchIcon />
              Buscar otro medicamento
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
