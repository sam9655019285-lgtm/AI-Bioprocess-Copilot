import { useState } from 'react'
import { addExperimentObservation } from '../api.js'
import ObservationTable from './ObservationTable.jsx'

const emptyValues = (fields) => Object.fromEntries(fields.map((f) => [f.name, '']))

function validate(fields, values) {
  const errors = {}
  for (const field of fields) {
    const raw = values[field.name].trim()
    if (raw === '') {
      if (field.required) errors[field.name] = 'This field is required.'
    } else if (field.type === 'number' && !Number.isFinite(Number(raw))) {
      errors[field.name] = 'Enter a number.'
    }
  }
  return errors
}

function toPayload(fields, values) {
  const payload = {}
  for (const field of fields) {
    const raw = values[field.name].trim()
    if (raw !== '') payload[field.name] = field.type === 'number' ? Number(raw) : raw
  }
  return payload
}

/** Split FastAPI's 422 detail list into per-field messages and general messages. */
function serverErrors(fields, detail) {
  const names = new Set(fields.map((f) => f.name))
  const byField = {}
  const general = []
  for (const err of Array.isArray(detail) ? detail : [{ msg: String(detail) }]) {
    const name = err.loc?.[1]
    if (names.has(name)) byField[name] = err.msg
    else general.push(err.msg)
  }
  return { byField, general }
}

export default function ManualEntryForm({ fields: allFields, experiment, onSaved }) {
  // The experiment comes from the picker, so it is not a form field here.
  const fields = allFields.filter((f) => f.name !== 'experiment_id')
  const [values, setValues] = useState(() => emptyValues(fields))
  const [fieldErrors, setFieldErrors] = useState({})
  const [result, setResult] = useState(null) // { type: 'success' | 'error', messages: [] }
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState([])

  function handleChange(name, value) {
    setValues((v) => ({ ...v, [name]: value }))
    setFieldErrors(({ [name]: _removed, ...rest }) => rest)
  }

  function handleReset() {
    setValues(emptyValues(fields))
    setFieldErrors({})
    setResult(null)
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setResult(null)
    if (!experiment) {
      setResult({ type: 'error', messages: ['Select or create an experiment first.'] })
      return
    }
    const errors = validate(fields, values)
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) {
      setResult({ type: 'error', messages: ['Please fix the highlighted fields.'] })
      return
    }

    setSubmitting(true)
    try {
      const response = await addExperimentObservation(experiment.experiment_id, toPayload(fields, values))
      setSubmitted((list) => [response.observation, ...list])
      setResult({ type: 'success', messages: [response.message] })
      onSaved?.()
    } catch (err) {
      if (err.status === 422 && Array.isArray(err.detail)) {
        const { byField, general } = serverErrors(fields, err.detail)
        setFieldErrors(byField)
        setResult({ type: 'error', messages: ['The backend rejected the observation.', ...general] })
      } else {
        setResult({ type: 'error', messages: [err.message] })
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <p className="muted">
        {experiment ? (
          <>
            Enter one time-point measurement for <strong>{experiment.experiment_id}</strong>. It is saved to the
            database.
          </>
        ) : (
          'Select or create an experiment above to save observations.'
        )}{' '}
        Fields marked <span className="required">*</span> are required.
      </p>

      <form onSubmit={handleSubmit} onReset={handleReset} noValidate>
        <div className="form-grid">
          {fields.map((field) => {
            const id = `obs-${field.name}`
            const error = fieldErrors[field.name]
            const isNotes = field.name === 'notes'
            const inputProps = {
              id,
              name: field.name,
              value: values[field.name],
              onChange: (e) => handleChange(field.name, e.target.value),
              'aria-invalid': Boolean(error),
              'aria-describedby': error ? `${id}-error` : undefined,
            }
            return (
              <div key={field.name} className={`field ${isNotes ? 'field-wide' : ''} ${error ? 'field-invalid' : ''}`}>
                <label htmlFor={id} title={field.description ?? undefined}>
                  {field.label}
                  {field.required && <span className="required"> *</span>}
                </label>
                <div className="input-with-unit">
                  {isNotes ? (
                    <textarea rows={2} {...inputProps} />
                  ) : (
                    <input type={field.type === 'number' ? 'number' : 'text'} step="any" {...inputProps} />
                  )}
                  {field.unit && <span className="unit">{field.unit}</span>}
                </div>
                {error && (
                  <span id={`${id}-error`} className="field-error">
                    {error}
                  </span>
                )}
              </div>
            )
          })}
        </div>

        <div className="actions">
          <button type="submit" disabled={submitting || !experiment}>
            {submitting ? 'Saving…' : 'Save observation'}
          </button>
          <button type="reset" className="secondary">
            Clear
          </button>
        </div>
      </form>

      {result && (
        <div className={`alert alert-${result.type}`} role="status">
          {result.messages.map((m) => (
            <div key={m}>{m}</div>
          ))}
        </div>
      )}

      {submitted.length > 0 && (
        <ObservationTable
          title={`Saved this session (${submitted.length})`}
          fields={allFields}
          observations={submitted}
        />
      )}
    </div>
  )
}
