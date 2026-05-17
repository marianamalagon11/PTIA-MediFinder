export default function LoadingOverlay({ message = 'Procesando...' }) {
  return (
    <div className="loading-overlay">
      <div className="spinner" />
      <p style={{ fontSize: 16, fontWeight: 500, color: '#4A5565' }}>{message}</p>
    </div>
  );
}
