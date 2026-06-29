interface Props {
  loading: boolean
  error: boolean
  empty?: boolean
  emptyMsg?: string
}

export default function PageSpinner({ loading, error, empty, emptyMsg = 'Aucune donnée disponible' }: Props) {
  if (loading) return (
    <div className="flex items-center justify-center py-16">
      <div style={{
        width: 28, height: 28, border: '3px solid #D5E8F5',
        borderTopColor: '#1A3A5C', borderRadius: '50%',
        animation: 'spin 0.7s linear infinite',
      }} />
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
  if (error) return (
    <div className="flex flex-col items-center justify-center py-16 gap-3">
      <p className="text-sm" style={{ color: '#C0391B' }}>
        ⚠ Impossible de joindre l'API — vérifiez qu'uvicorn est démarré.
      </p>
      <button
        onClick={() => { localStorage.clear(); window.location.replace('/login') }}
        className="text-xs px-3 py-1.5 rounded-lg border"
        style={{ borderColor: '#C0391B', color: '#C0391B' }}
      >
        Reconnecter (vider la session)
      </button>
    </div>
  )
  if (empty) return (
    <div className="flex items-center justify-center py-16">
      <p className="text-sm" style={{ color: '#5D6D7E' }}>{emptyMsg}</p>
    </div>
  )
  return null
}
