import { useEffect, useState } from 'react'
import { createExperiment, listExperiments } from '../api.js'
import SourceBadge, { SOURCE_LABELS } from './SourceBadge.jsx'

export const SCALES = [1, 10, 100, 1000]

function CreateExperimentForm({ sources, defaultSource, onCreated, onCancel }) {
  const [values, setValues] = useState({
    experiment_id: '',
    name: '',
    scale_liters: '1',
    data_source: defaultSource,
    description: '',
    notes: '',
  })
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const set = (name) => (e) => setValues({ ...values, [name]: e.target.value })

  async function handleSubmit(event) {
    event.preventDefault()
    if (!values.experiment_id.trim() || !values.name.trim()) {
      setError('Experiment ID and name are required.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const payload = { ...values, scale_liters: Number(values.scale_liters) }
      for (const key of ['description', 'notes']) if (!payload[key].trim()) delete payload[key]
      onCreated(await createExperiment(payload))
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="create-experiment" onSubmit={handleSubmit} noValidate>
      <h4>New experiment</h4>
      <div className="config-grid">
        <label className="field">
          <span>Experiment ID *</span>
          <input value={values.experiment_id} onChange={set('experiment_id')} placeholder="e.g. EXP-002" />
        </label>
        <label className="field">
          <span>Name *</span>
          <input value={values.name} onChange={set('name')} placeholder="e.g. CHO fed-batch run 2" />
        </label>
        <label className="field">
          <span>Scale</span>
          <select value={values.scale_liters} onChange={set('scale_liters')}>
            {SCALES.map((s) => (
              <option key={s} value={s}>
                {s} L
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Data source</span>
          <select value={values.data_source} onChange={set('data_source')} disabled={sources.length === 1}>
            {sources.map((s) => (
              <option key={s} value={s}>
                {SOURCE_LABELS[s]}
              </option>
            ))}
          </select>
        </label>
        <label className="field field-wide">
          <span>Description</span>
          <input value={values.description} onChange={set('description')} />
        </label>
        <label className="field field-wide">
          <span>Notes</span>
          <input value={values.notes} onChange={set('notes')} />
        </label>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="actions">
        <button type="submit" disabled={saving}>
          {saving ? 'Creating…' : 'Create experiment'}
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

/**
 * Select a stored experiment (limited to `sources`) or create a new one.
 * `value` is the selected experiment object or null; `version` changes trigger a reload.
 */
export default function ExperimentPicker({
  sources,
  defaultSource = sources[0],
  value,
  onChange,
  onCreated,
  version,
  disabled = false,
  noneLabel = '— Select an experiment —',
  allowCreate = true,
  label = 'Experiment',
}) {
  const [experiments, setExperiments] = useState(null)
  const [error, setError] = useState(null)
  const [creating, setCreating] = useState(false)
  const sourcesKey = sources.join(',')

  useEffect(() => {
    let cancelled = false
    listExperiments()
      .then((all) => {
        if (cancelled) return
        setExperiments(all.filter((e) => sourcesKey.split(',').includes(e.data_source)))
        setError(null)
      })
      .catch((err) => !cancelled && setError(`Could not load experiments: ${err.message}`))
    return () => {
      cancelled = true
    }
  }, [version, sourcesKey])

  // Clear the selection if the experiment was deleted elsewhere (e.g. on the History page).
  const selectedMissing = Boolean(value && experiments && !experiments.some((e) => e.experiment_id === value.experiment_id))
  useEffect(() => {
    if (selectedMissing) onChange(null)
  }, [selectedMissing, onChange])

  // Fresh copy of the selected experiment (up-to-date observation count).
  const selected = value && (experiments?.find((e) => e.experiment_id === value.experiment_id) ?? value)

  function handleCreated(experiment) {
    setCreating(false)
    setExperiments((list) => [experiment, ...(list ?? []).filter((e) => e.experiment_id !== experiment.experiment_id)])
    onChange(experiment)
    onCreated?.(experiment)
  }

  return (
    <div className="picker">
      <div className="picker-row">
        <label className="field picker-select">
          <span>{label}</span>
          <select
            value={value?.experiment_id ?? ''}
            disabled={disabled}
            onChange={(e) => onChange(experiments?.find((x) => x.experiment_id === e.target.value) ?? null)}
          >
            <option value="">{noneLabel}</option>
            {(experiments ?? []).map((e) => (
              <option key={e.experiment_id} value={e.experiment_id}>
                {e.experiment_id} — {e.name} ({e.scale_liters} L, {SOURCE_LABELS[e.data_source]})
              </option>
            ))}
          </select>
        </label>
        {allowCreate && (
          <button type="button" className="secondary" disabled={disabled} onClick={() => setCreating((c) => !c)}>
            {creating ? 'Close' : '+ New experiment'}
          </button>
        )}
      </div>
      {selected && (
        <p className="muted picker-summary">
          <SourceBadge source={selected.data_source} /> {selected.name} · {selected.scale_liters} L
          {/* While locked (e.g. during a run) the count would be stale, so it is hidden. */}
          {!disabled && ` · ${selected.observation_count} saved observation(s)`}
        </p>
      )}
      {error && <div className="alert alert-error">{error}</div>}
      {creating && !disabled && (
        <CreateExperimentForm
          sources={sources}
          defaultSource={defaultSource}
          onCreated={handleCreated}
          onCancel={() => setCreating(false)}
        />
      )}
    </div>
  )
}
