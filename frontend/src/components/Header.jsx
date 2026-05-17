import { useNavigate } from 'react-router-dom';

const ArrowLeft = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M19 12H5M12 5l-7 7 7 7" />
  </svg>
);

export default function Header({ showBack = false }) {
  const navigate = useNavigate();

  return (
    <header style={{
      background: '#FFFFFF',
      borderBottom: '1px solid #F3F4F6',
      height: 81,
      display: 'flex',
      alignItems: 'center',
      position: 'sticky',
      top: 0,
      zIndex: 100,
      boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
    }}>
      <div style={{
        maxWidth: 1280,
        width: '100%',
        margin: '0 auto',
        padding: '0 32px',
        display: 'flex',
        alignItems: 'center',
        gap: 16,
      }}>
        {showBack && (
          <button
            onClick={() => navigate(-1)}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: '#4A5565',
              display: 'flex',
              alignItems: 'center',
              padding: '8px',
              borderRadius: 8,
              transition: 'background 0.15s',
            }}
            onMouseEnter={e => e.currentTarget.style.background = '#F3F4F6'}
            onMouseLeave={e => e.currentTarget.style.background = 'none'}
            aria-label="Volver"
          >
            <ArrowLeft />
          </button>
        )}
        <img
          src="/logo.png"
          alt="MediFinder"
          style={{ height: 48, width: 'auto', cursor: 'pointer' }}
          onClick={() => navigate('/')}
        />
      </div>
    </header>
  );
}
