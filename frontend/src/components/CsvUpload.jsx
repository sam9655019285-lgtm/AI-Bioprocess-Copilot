import { useRef, useState } from 'react'
import { uploadExperimentCsv } from '../api.js'
import ObservationTable from './ObservationTable.jsx'

function downloadTemplate(fields) {
  const blob = new Blob([fields.map((f) => f.name).join(',') + '\n'], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'observations_template.csv'
  link.click()
  URL.revokeObjectURL(url)
}

export default function CsvUpload({ fields, experiment, onSaved }) {
  const inputRef = useRef(null)
  const [file, setFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  async function handleUpload(event) {
    event.preventDefault()
    if (!experiment) {
      setError('Select or create an experiment first.')
      return
    }
    if (!file) {
      setError('Choose a CSV file first.')
      return
    }
    setUploading(true)
    setError(null)
    setResult(null)
    try {
      setResult(await uploadExperimentCsv(experiment.experiment_id, file))
      onSaved?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setUploading(false)
    }
  }

  function handleClear() {
    setFile(null)
    setResult(null)
    setError(null)
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <div>
      <details className="columns-help">
        <summary>Expected CSV columns</summary>
        <p className="muted">
          First row must be a header with these column names (any order). Required columns must be present and
          filled on every row; optional columns may be omitted or left empty. Unknown columns are ignored. When
          saving to an experiment, <code>experiment_id</code> may be omitted or left empty; rows naming a different
          experiment are rejected.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Column</th>
                <th>Unit</th>
                <th>Type</th>
                <th>Required</th>
              </tr>
            </thead>
            <tbody>
              {fields.map((f) => (
                <tr key={f.name}>
                  <td><code>{f.name}</code></td>
                  <td>{f.unit ?? '—'}</td>
                  <td>{f.type}</td>
                  <td>{f.name === 'experiment_id' ? 'Optional when saving' : f.required ? 'Yes' : 'No'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button type="button" className="secondary" onClick={() => downloadTemplate(fields)}>
          Download CSV template
        </button>
      </details>

      <form className="upload-row" onSubmit={handleUpload}>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          aria-label="CSV file"
          onChange={(e) => {
            setFile(e.target.files[0] ?? null)
            setError(null)
          }}
        />
        <div className="actions">
          <button type="submit" disabled={uploading || !experiment}>
            {uploading ? 'Uploading…' : 'Upload & Save'}
          </button>
          <button type="button" className="secondary" onClick={handleClear}>
            Clear
          </button>
        </div>
      </form>

      {error && (
        <p className="alert alert-error" role="status">
          Upload failed: {error}
        </p>
      )}

      {result && (
        <>
          <div className={`alert ${result.rejected_count ? 'alert-warning' : 'alert-success'}`} role="status">
            <strong>{result.filename}</strong>: {result.total_rows} row(s) read, {result.accepted_count} accepted,{' '}
            {result.rejected_count} rejected. Saved {result.saved_count} observation(s) to{' '}
            <strong>{result.experiment_id}</strong>.
            {result.ignored_columns.length > 0 && (
              <div>Ignored unknown column(s): {result.ignored_columns.join(', ')}</div>
            )}
          </div>

          {result.errors.length > 0 && (
            <div className="table-wrap">
              <table className="error-table">
                <caption>Validation errors</caption>
                <thead>
                  <tr>
                    <th>CSV line</th>
                    <th>Column</th>
                    <th>Value</th>
                    <th>Problem</th>
                  </tr>
                </thead>
                <tbody>
                  {result.errors.map((e, i) => (
                    <tr key={i}>
                      <td>{e.row}</td>
                      <td>{e.field ? <code>{e.field}</code> : '—'}</td>
                      <td>{e.value ?? '—'}</td>
                      <td>{e.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {result.observations.length > 0 && (
            <ObservationTable
              title={`Accepted observations (${result.accepted_count})`}
              fields={fields}
              observations={result.observations}
            />
          )}
        </>
      )}
    </div>
  )
}
