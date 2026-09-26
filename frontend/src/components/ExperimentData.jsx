import { useEffect, useState } from 'react'
import { getObservationSchema } from '../api.js'
import CsvUpload from './CsvUpload.jsx'
import ExperimentPicker from './ExperimentPicker.jsx'
import ManualEntryForm from './ManualEntryForm.jsx'

const MODES = [
  { id: 'manual', label: 'Manual Entry' },
  { id: 'csv', label: 'CSV Upload' },
]

export default function ExperimentData({ dataVersion, onDataChanged }) {
  const [fields, setFields] = useState(null)
  const [error, setError] = useState(null)
  const [mode, setMode] = useState('manual')
  const [experiment, setExperiment] = useState(null)

  useEffect(() => {
    getObservationSchema()
      .then(setFields)
      .catch((err) => setError(err.message))
  }, [])

  return (
    <section className="card">
      <div className="card-header">
        <h2>Experiment Data</h2>
        <div className="segmented" role="tablist" aria-label="Input method">
          {MODES.map((m) => (
            <button
              key={m.id}
              role="tab"
              aria-selected={mode === m.id}
              className={mode === m.id ? 'active' : ''}
              onClick={() => setMode(m.id)}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <p className="alert alert-error">
          Could not load the observation schema: {error}. Is the FastAPI server running on port 8000?
        </p>
      )}
      {!fields && !error && <p className="muted">Loading…</p>}

      <ExperimentPicker
        sources={['manual', 'csv']}
        defaultSource={mode}
        value={experiment}
        onChange={setExperiment}
        onCreated={onDataChanged}
        version={dataVersion}
      />

      {fields && (
        <>
          {/* Both stay mounted so switching modes keeps entered data and results. */}
          <div hidden={mode !== 'manual'}>
            <ManualEntryForm fields={fields} experiment={experiment} onSaved={onDataChanged} />
          </div>
          <div hidden={mode !== 'csv'}>
            <CsvUpload fields={fields} experiment={experiment} onSaved={onDataChanged} />
          </div>
        </>
      )}
    </section>
  )
}
