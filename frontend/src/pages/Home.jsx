import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Header from '../components/Header';
import LoadingOverlay from '../components/LoadingOverlay';
import { realizarOCR } from '../api/medifinder';

/* ─── Icons ──────────────────────────────────────────────────────────────────── */
const CameraIcon = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/>
    <circle cx="12" cy="13" r="4"/>
  </svg>
);
const UploadIcon = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="16 16 12 12 8 16"/>
    <line x1="12" y1="12" x2="12" y2="21"/>
    <path d="M20.39 18.39A5 5 0 0018 9h-1.26A8 8 0 103 16.3"/>
  </svg>
);
const LightbulbIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="9" y1="18" x2="15" y2="18"/>
    <line x1="10" y1="22" x2="14" y2="22"/>
    <path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0018 8 6 6 0 006 8c0 1 .23 2.23 1.5 3.5A4.61 4.61 0 018.91 14"/>
  </svg>
);
const XIcon = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
  </svg>
);
const ShutterIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10"/>
    <circle cx="12" cy="12" r="4" fill="currentColor"/>
  </svg>
);

/* ─── Text extractors ─────────────────────────────────────────────────────────── */
function extraerConcentracion(texto) {
  const m = texto.match(/(\d+[\.,]?\d*)\s*(mg|mcg|g\b|ml|ui|%)/i);
  return m ? `${m[1]} ${m[2].toLowerCase()}` : '';
}
function extraerForma(texto) {
  const formas = ['tableta', 'capsula', 'comprimido', 'ampolla', 'jarabe', 'suspension', 'crema', 'pomada', 'supositorio', 'parche', 'solucion', 'solución', 'inyectable', 'gotas'];
  const tl = texto.toLowerCase();
  return formas.find(f => tl.includes(f)) || '';
}
function extraerInvima(texto) {
  const m = texto.match(/invima[\s:\-]*[\w\-]+/i);
  return m ? m[0] : '';
}
function errorLegible(e) {
  if (e.message?.toLowerCase().includes('fetch') || e.message?.toLowerCase().includes('network')) {
    return 'No se puede conectar al servidor. Asegúrate de que el backend esté corriendo en el puerto 8002 (cd python-service && python main.py).';
  }
  return e.message || 'Error inesperado al procesar la imagen.';
}

/* ─── Camera Modal ────────────────────────────────────────────────────────────── */
function CameraModal({ onCapture, onClose }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const [ready, setReady] = useState(false);
  const [camError, setCamError] = useState('');

  useEffect(() => {
    const constraints = { video: { facingMode: 'environment', width: { ideal: 1920 }, height: { ideal: 1080 } } };
    navigator.mediaDevices.getUserMedia(constraints)
      .then(stream => {
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
      })
      .catch(() => {
        // retry with any camera
        navigator.mediaDevices.getUserMedia({ video: true })
          .then(stream => {
            streamRef.current = stream;
            if (videoRef.current) videoRef.current.srcObject = stream;
          })
          .catch(err => {
            setCamError('No se pudo acceder a la cámara: ' + (err.message || 'permiso denegado.'));
          });
      });

    return () => {
      streamRef.current?.getTracks().forEach(t => t.stop());
    };
  }, []);

  function capture() {
    const video = videoRef.current;
    if (!video) return;
    const canvas = document.createElement('canvas');
    canvas.width  = video.videoWidth  || 1280;
    canvas.height = video.videoHeight || 720;
    canvas.getContext('2d').drawImage(video, 0, 0);
    canvas.toBlob(blob => {
      const file = new File([blob], 'foto_medicamento.jpg', { type: 'image/jpeg' });
      streamRef.current?.getTracks().forEach(t => t.stop());
      onCapture(file);
    }, 'image/jpeg', 0.95);
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.92)',
      zIndex: 9999, display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center', gap: 20,
    }}>
      {/* Close */}
      <button
        onClick={() => { streamRef.current?.getTracks().forEach(t => t.stop()); onClose(); }}
        style={{
          position: 'absolute', top: 20, right: 20,
          background: 'rgba(255,255,255,0.15)', border: 'none', borderRadius: '50%',
          width: 44, height: 44, cursor: 'pointer', color: '#fff',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}
      >
        <XIcon />
      </button>

      {camError ? (
        <div style={{ color: '#FCA5A5', fontSize: 16, textAlign: 'center', maxWidth: 400, padding: 24 }}>
          {camError}
          <br /><br />
          <button className="btn btn-secondary" onClick={onClose}>Cerrar</button>
        </div>
      ) : (
        <>
          <p style={{ color: '#fff', fontSize: 14, opacity: 0.7 }}>Apunta la cámara al medicamento</p>
          <div style={{
            position: 'relative', borderRadius: 16, overflow: 'hidden',
            border: '2px solid rgba(255,255,255,0.2)',
            maxWidth: '90vw', maxHeight: '65vh',
          }}>
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              onCanPlay={() => setReady(true)}
              style={{ display: 'block', maxWidth: '90vw', maxHeight: '65vh', objectFit: 'cover' }}
            />
            {/* Viewfinder overlay */}
            <div style={{
              position: 'absolute', inset: 0, border: '2px solid transparent',
              boxShadow: 'inset 0 0 0 40px rgba(0,0,0,0.15)',
              pointerEvents: 'none',
            }} />
          </div>

          <button
            onClick={capture}
            disabled={!ready}
            style={{
              width: 72, height: 72, borderRadius: '50%',
              background: ready ? 'linear-gradient(135deg,#2B7FFF,#155DFC)' : '#555',
              border: '4px solid rgba(255,255,255,0.5)',
              cursor: ready ? 'pointer' : 'not-allowed',
              color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
              transition: 'transform 0.1s',
            }}
            onMouseDown={e => { if (ready) e.currentTarget.style.transform = 'scale(0.93)'; }}
            onMouseUp={e => { e.currentTarget.style.transform = 'scale(1)'; }}
            aria-label="Tomar foto"
          >
            <ShutterIcon />
          </button>
          {!ready && <p style={{ color: '#9CA3AF', fontSize: 13 }}>Iniciando cámara...</p>}
        </>
      )}
    </div>
  );
}

/* ─── Home Page ───────────────────────────────────────────────────────────────── */
export default function Home() {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState('');
  const [showCamera, setShowCamera] = useState(false);

  async function procesarImagen(file) {
    if (!file) return;
    setError('');
    setLoading(true);
    const imagenUrl = URL.createObjectURL(file);
    try {
      const ocrResult = await realizarOCR(file);
      navigate('/verificar', {
        state: {
          imagenUrl,
          ocrResult,
          prefilledFields: {
            nombreComercial:  ocrResult.nombre_detectado || '',
            principioActivo:  '',
            concentracion:    extraerConcentracion(ocrResult.texto_completo || ''),
            formaFarmaceutica: extraerForma(ocrResult.texto_completo || ''),
            registroInvima:   extraerInvima(ocrResult.texto_completo || ''),
          },
        },
      });
    } catch (e) {
      setError(errorLegible(e));
    } finally {
      setLoading(false);
    }
  }

  function onFileChange(e) {
    const file = e.target.files?.[0];
    if (file) procesarImagen(file);
    e.target.value = '';
  }

  function abrirCamara() {
    if (!navigator.mediaDevices?.getUserMedia) {
      // Fallback: device file picker with capture
      fileInputRef.current?.click();
      return;
    }
    setShowCamera(true);
  }

  return (
    <div style={{ minHeight: '100vh', background: '#FFFFFF', display: 'flex', flexDirection: 'column' }}>
      {loading && <LoadingOverlay message="Analizando imagen con OCR..." />}
      {showCamera && (
        <CameraModal
          onCapture={file => { setShowCamera(false); procesarImagen(file); }}
          onClose={() => setShowCamera(false)}
        />
      )}

      <Header />

      <main style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '48px 32px' }}>
        <div style={{
          maxWidth: 896, width: '100%',
          display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 48, alignItems: 'center',
        }}>

          {/* ─── Left column ─── */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <h1 style={{ fontSize: 28, fontWeight: 600, color: '#1E2939', lineHeight: 1.3 }}>
                Encuentra tu<br />medicamento
              </h1>
              <p style={{ fontSize: 18, color: '#4A5565', lineHeight: 1.6 }}>
                Identifica medicamentos y encuentra alternativas disponibles en Colombia usando inteligencia artificial.
              </p>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {/* Camera button */}
              <button
                className="btn btn-primary btn-full"
                onClick={abrirCamara}
                disabled={loading}
                style={{ height: 64, fontSize: 16 }}
              >
                <CameraIcon />
                Tomar foto
              </button>

              {/* File picker button */}
              <button
                className="btn btn-secondary btn-full"
                onClick={() => fileInputRef.current?.click()}
                disabled={loading}
                style={{ height: 64, fontSize: 16 }}
              >
                <UploadIcon />
                Subir imagen
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={onFileChange}
                style={{ display: 'none' }}
              />
            </div>

            {/* Error */}
            {error && (
              <div className="error-banner">
                <span style={{ flexShrink: 0 }}>⚠️</span>
                <span>{error}</span>
              </div>
            )}

            {/* Tip */}
            <div style={{
              background: '#EFF6FF', borderRadius: 12, padding: '14px 18px',
              display: 'flex', alignItems: 'flex-start', gap: 10,
            }}>
              <span style={{ marginTop: 1, color: '#193CB8', flexShrink: 0 }}><LightbulbIcon /></span>
              <p style={{ fontSize: 14, color: '#193CB8', lineHeight: 1.5 }}>
                <strong>Consejo:</strong> Usa buena iluminación y evita reflejos para obtener mejores resultados de detección.
              </p>
            </div>
          </div>

          {/* ─── Right panel ─── */}
          <div style={{
            background: 'linear-gradient(135deg, #DBEAFE 0%, #DCFCE7 100%)',
            borderRadius: 24, display: 'flex', alignItems: 'center', justifyContent: 'center',
            minHeight: 320, padding: 32,
          }}>
            <img src="/logo.png" alt="MediFinder" style={{ maxWidth: 220, maxHeight: 200, objectFit: 'contain' }} />
          </div>
        </div>
      </main>
    </div>
  );
}
