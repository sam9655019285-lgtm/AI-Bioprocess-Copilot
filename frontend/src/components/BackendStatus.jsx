import { useCallback, useEffect, useState } from 'react'
import { getHealth } from '../api.js'

export default function BackendStatus() {
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const checkHealth = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setHealth(await getHealth())
    } catch (err) {
      setHealth(null)
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    checkHealth()
  }, [checkHealth])

  const status = loading ? 'checking' : error ? 'offline' : 'online'

  return (
    <section className="card">
      <div className="card-header">
        <h2>Backend status</h2>
        <span className={`badge badge-${status}`}>{status}</span>
      </div>

      {error && (
        <p className="error">
          Could not reach the backend: {error}. Is the FastAPI server running on port 8000?
        </p>
      )}

      {health && (
        <dl className="details">
          <dt>Service</dt>
          <dd>{health.service}</dd>
          <dt>Version</dt>
          <dd>{health.version}</dd>
          <dt>Data source</dt>
          <dd>{health.data_source}</dd>
          <dt>Server time (UTC)</dt>
          <dd>{health.timestamp}</dd>
        </dl>
      )}

      <button onClick={checkHealth} disabled={loading}>
        {loading ? 'Checking…' : 'Check again'}
      </button>
    </section>
  )
}
