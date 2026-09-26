import { useEffect, useState } from 'react'
import { getExperimentAnalysis, simulateScaleUp } from '../api.js'
import AdvancedScaleUpModeling from './AdvancedScaleUpModeling.jsx'
import ExperimentPicker from './ExperimentPicker.jsx'
import MetricCard from './MetricCard.jsx'
import ScaleUpSeries from './ScaleUpSeries.jsx'
import SourceBadge from './SourceBadge.jsx'

const QUICK_SCALES = [1, 10, 100, 1000]
const QUICK_FACTORS = [10, 100, 1000]

// Scenario controls: request field, source parameter used to initialise it, label, unit.
const CONTROLS = [
  { key: 'target_temperature_c', param: 'temperature_c', label: 'Temperature', unit: '°C' },
  { key: 'target_ph', param: 'ph', label: 'pH', unit: '' },
  { key: 'target_dissolved_oxygen_percent', param: 'dissolved_oxygen_percent', label: 'DO target', unit: '% air sat.' },
  { key: 'target_agitation_rpm', param: 'agitation_rpm', label: 'Agitation', unit: 'rpm' },
  { key: 'target_aeration_vvm', param: 'aeration_rate', label: 'Aeration', unit: 'vvm' },
  { key: 'target_feed_rate_ml_per_h', param: 'feed_rate', label: 'Feed rate', unit: 'mL/h' },
]

// Display decimals per compared parameter (formatting only).
const DECIMALS = {
  temperature_c: 2,
  ph: 2,
  dissolved_oxygen_percent: 1,
  agitation_rpm: 0,
  aeration_rate: 3,
  feed_rate: 2,
  cell_density: 2,
  culture_duration_hours: 1,
}

const TREATMENT_CLASS = {
  Preserved: 'treat-preserved',
  'Scenario setting': 'treat-scenario',
  'Baseline assumption': 'treat-baseline',
  'Not available': 'treat-na',
}

/** Up to `digits` decimals, thousands separators, no trailing zeros. */
const num = (value, digits = 3) => value.toLocaleString('en-US', { maximumFractionDigits: digits })
const signed = (value, digits) => {
  const text = num(value, digits)
  return value > 0 ? `+${text}` : text === '-0' ? '0' : text
}

/** Latest recorded value of each parameter (from the Phase 5 analysis). */
function sourceValues(analysis) {
  return Object.fromEntries(analysis.parameters.map((p) => [p.parameter, p.final]))
}

function initialControls(analysis) {
  const values = sourceValues(analysis)
  return Object.fromEntries(CONTROLS.map((c) => [c.key, values[c.param] == null ? '' : String(values[c.param])]))
}

function defaultTarget(sourceScale) {
  return String(QUICK_SCALES.find((s) => s > sourceScale) ?? sourceScale * 10)
}

function buildRequest(experimentId, targetScale, controls) {
  const request = { source_experiment_id: experimentId, target_scale_liters: Number(targetScale) }
  for (const c of CONTROLS) {
    const raw = controls[c.key].trim()
    if (raw !== '') request[c.key] = Number(raw)
  }
  return request
}

function validate(targetScale, controls) {
  const errors = {}
  const scale = Number(targetScale)
  if (targetScale.trim() === '' || !Number.isFinite(scale) || scale <= 0) {
    errors.target_scale_liters = 'Enter a target scale greater than 0 L.'
  }
  for (const c of CONTROLS) {
    const raw = controls[c.key].trim()
    if (raw !== '' && !Number.isFinite(Number(raw))) errors[c.key] = 'Enter a number.'
  }
  return errors
}

function ComparisonTable({ parameters }) {
  return (
    <div className="table-wrap">
      <table className="comparison-table">
        <thead>
          <tr>
            <th>Parameter</th>
            <th>Source</th>
            <th>Target scenario</th>
            <th>Change</th>
            <th>Treatment</th>
            <th>Needs engineering validation</th>
          </tr>
        </thead>
        <tbody>
          {parameters.map((p) => {
            const d = DECIMALS[p.parameter] ?? 2
            const unit = p.unit ? ` ${p.unit}` : ''
            return (
              <tr key={p.parameter}>
                <td>{p.label}</td>
                <td className="num">{p.source == null ? '—' : `${num(p.source, d)}${unit}`}</td>
                <td className="num">{p.target == null ? 'not specified' : `${num(p.target, d)}${unit}`}</td>
                <td className="num">
                  {p.change == null ? '—' : signed(p.change, d)}
                  {p.percent_change != null && p.change !== 0 && (
                    <span className="muted"> ({signed(p.percent_change, 1)}%)</span>
                  )}
                </td>
                <td>
                  <span className={`treat-badge ${TREATMENT_CLASS[p.treatment] ?? ''}`}>{p.treatment}</span>
                </td>
                <td className="validation-note">{p.validation_note}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function DerivedCalculations({ result }) {
  const s = result.source.scale_liters
  const t = result.target_scale_liters
  const { gas_flow: g, feed: f, agitation: a } = result
  return (
    <div className="derived-grid">
      <div className="derived">
        <h4>Gas flow (aeration × volume)</h4>
        <dl className="details">
          <dt>Source</dt>
          <dd>{g.source_l_per_min == null ? 'no aeration recorded' : `${num(g.source_vvm)} vvm × ${num(s)} L = ${num(g.source_l_per_min)} L/min`}</dd>
          <dt>Target</dt>
          <dd>
            {g.target_l_per_min == null
              ? 'no target aeration specified'
              : `${num(g.target_vvm)} vvm × ${num(t)} L = ${num(g.target_l_per_min)} L/min (${num(g.target_l_per_h)} L/h)`}
          </dd>
          <dt>Gas flow ratio</dt>
          <dd>{g.ratio == null ? '—' : `${num(g.ratio, 2)}× the source gas flow`}</dd>
        </dl>
      </div>
      <div className="derived">
        <h4>Feed</h4>
        <dl className="details">
          <dt>Source</dt>
          <dd>{f.source_ml_per_h == null ? 'no feed recorded' : `${num(f.source_ml_per_h)} mL/h = ${num(f.source_ml_per_h_per_l)} mL/h per L`}</dd>
          <dt>Target</dt>
          <dd>{f.target_ml_per_h == null ? 'no target feed specified' : `${num(f.target_ml_per_h)} mL/h = ${num(f.target_ml_per_h_per_l)} mL/h per L`}</dd>
          <dt>Same feed per litre</dt>
          <dd>{f.volume_proportional_ml_per_h == null ? '—' : `${num(f.volume_proportional_ml_per_h)} mL/h (source × ${num(result.scale_factor)})`}</dd>
          <dt>Total over baseline</dt>
          <dd>
            {f.target_total_feed_ml == null
              ? '—'
              : `${num(f.target_ml_per_h)} mL/h × ${num(f.baseline_duration_hours)} h = ${num(f.target_total_feed_ml)} mL (${num(f.target_total_feed_ml / 1000)} L), constant rate`}
          </dd>
        </dl>
      </div>
      <div className="derived">
        <h4>Agitation</h4>
        <dl className="details">
          <dt>Source</dt>
          <dd>{a.source_rpm == null ? '—' : `${num(a.source_rpm)} rpm`}</dd>
          <dt>Target</dt>
          <dd>{a.target_rpm == null ? 'not specified' : `${num(a.target_rpm)} rpm`}</dd>
          <dt>Change</dt>
          <dd>{a.change_rpm == null ? '—' : `${signed(a.change_rpm, 1)} rpm`}</dd>
        </dl>
        <p className="muted small-note">{a.note}</p>
      </div>
    </div>
  )
}

/** Transparent, illustrative scale-up scenario for a stored experiment (read-only). */
export default function ScaleUpSimulator({ active, dataVersion, onScaleUpScenario, onOpenComparison }) {
  const [experiment, setExperiment] = useState(null)
  const [source, setSource] = useState(null) // Phase 5 analysis of the source experiment
  const [targetScale, setTargetScale] = useState('')
  const [controls, setControls] = useState(null)
  const [fieldErrors, setFieldErrors] = useState({})
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [resultKey, setResultKey] = useState(null)
  const [running, setRunning] = useState(false)
  const experimentId = experiment?.experiment_id

  // Load the source experiment and initialise the scenario from its latest values.
  useEffect(() => {
    setResult(null)
    setError(null)
    setFieldErrors({})
    if (!experimentId) {
      setSource(null)
      return
    }
    let cancelled = false
    getExperimentAnalysis(experimentId)
      .then((analysis) => {
        if (cancelled) return
        setSource(analysis)
        setControls(initialControls(analysis))
        setTargetScale(defaultTarget(analysis.experiment.scale_liters))
      })
      .catch((err) => !cancelled && setError(`Could not load the source experiment: ${err.message}`))
    return () => {
      cancelled = true
    }
  }, [experimentId])

  const loaded = source?.experiment.experiment_id === experimentId ? source : null
  const sourceScale = loaded?.experiment.scale_liters
  const latest = loaded ? sourceValues(loaded) : {}
  const requestKey = loaded ? JSON.stringify(buildRequest(experimentId, targetScale, controls)) : null
  const stale = result && requestKey !== resultKey

  function setControl(key, value) {
    setControls((c) => ({ ...c, [key]: value }))
    setFieldErrors(({ [key]: _removed, ...rest }) => rest)
  }

  function chooseScale(value) {
    setTargetScale(String(value))
    setFieldErrors(({ target_scale_liters: _removed, ...rest }) => rest)
  }

  async function handleSimulate(event) {
    event.preventDefault()
    setError(null)
    const errors = validate(targetScale, controls)
    setFieldErrors(errors)
    if (Object.keys(errors).length) return
    const request = buildRequest(experimentId, targetScale, controls)
    setRunning(true)
    try {
      setResult(await simulateScaleUp(request))
      setResultKey(JSON.stringify(request))
      onScaleUpScenario?.(experimentId, request)
    } catch (err) {
      if (err.status === 422 && Array.isArray(err.detail)) {
        setFieldErrors(Object.fromEntries(err.detail.map((e) => [e.loc?.[1], e.msg])))
        setError('The scenario was rejected; check the highlighted inputs.')
      } else {
        setError(err.message)
      }
    } finally {
      setRunning(false)
    }
  }

  return (
    <section className="card scaleup">
      <div className="card-header">
        <h2>Scale-Up Simulator</h2>
        <span className="treat-badge treat-scenario">Illustrative simulation</span>
      </div>
      <p className="alert alert-warning scaleup-note">
        These results are illustrative scenario estimates, not validated predictions for a specific cell line or
        bioreactor. Only transparent calculations are made (scale factor, volumes, gas flow from vvm, feed per litre);
        no engineering scale-up law is applied.
      </p>

      <ExperimentPicker
        sources={['manual', 'csv', 'simulated']}
        value={experiment}
        onChange={setExperiment}
        version={dataVersion}
        allowCreate={false}
        noneLabel="— Select a source experiment —"
      />
      {error && <div className="alert alert-error">{error}</div>}
      {!experimentId && <p className="muted placeholder">Select a stored experiment as the scale-up source.</p>}

      {loaded && controls && (
        <form onSubmit={handleSimulate} noValidate>
          <div className="scaleup-source">
            <div>
              <div className="muted small-label">Source</div>
              <strong>{loaded.experiment.name}</strong> <SourceBadge source={loaded.experiment.data_source} />
            </div>
            <div>
              <div className="muted small-label">Source scale</div>
              <strong>{num(sourceScale)} L</strong>
            </div>
            <div>
              <div className="muted small-label">Observations</div>
              <strong>{loaded.observation_count}</strong>
            </div>
            <div>
              <div className="muted small-label">Latest culture time</div>
              <strong>{loaded.culture_end_hours == null ? '—' : `${num(loaded.culture_end_hours, 2)} h`}</strong>
            </div>
          </div>
          {loaded.observation_count === 0 && (
            <div className="alert alert-warning">
              This experiment has no observations, so there are no source values. You can still enter scenario
              settings; comparisons with the source will show “—”.
            </div>
          )}

          <h3>Target scale</h3>
          <div className="scale-options">
            <div className="chip-group" aria-label="Target volume">
              {QUICK_SCALES.map((s) => (
                <button
                  type="button"
                  key={s}
                  className={`chip ${Number(targetScale) === s ? 'chip-active' : ''}`}
                  onClick={() => chooseScale(s)}
                >
                  {s} L
                </button>
              ))}
            </div>
            <div className="chip-group" aria-label="Scale factor">
              {QUICK_FACTORS.map((f) => (
                <button
                  type="button"
                  key={f}
                  className={`chip ${Number(targetScale) === sourceScale * f ? 'chip-active' : ''}`}
                  onClick={() => chooseScale(sourceScale * f)}
                >
                  {f}×
                </button>
              ))}
            </div>
            <label className={`field target-scale ${fieldErrors.target_scale_liters ? 'field-invalid' : ''}`}>
              <span>Custom target volume</span>
              <span className="input-with-unit">
                <input
                  name="target_scale_liters"
                  type="number"
                  step="any"
                  min="0"
                  value={targetScale}
                  onChange={(e) => chooseScale(e.target.value)}
                />
                <span className="unit">L</span>
              </span>
              {fieldErrors.target_scale_liters && <span className="field-error">{fieldErrors.target_scale_liters}</span>}
            </label>
          </div>

          <div className="card-header scenario-header">
            <h3>Scenario settings</h3>
            <button type="button" className="secondary small" onClick={() => setControls(initialControls(loaded))}>
              Use source experiment values
            </button>
          </div>
          <p className="muted small-note">
            Pre-filled with the latest recorded value of each parameter. Leave a field empty to leave it unspecified.
          </p>
          <div className="config-grid">
            {CONTROLS.map((c) => (
              <label key={c.key} className={`field ${fieldErrors[c.key] ? 'field-invalid' : ''}`}>
                <span>{c.label}</span>
                <span className="input-with-unit">
                  <input
                    name={c.key}
                    type="number"
                    step="any"
                    value={controls[c.key]}
                    onChange={(e) => setControl(c.key, e.target.value)}
                  />
                  {c.unit && <span className="unit">{c.unit}</span>}
                </span>
                <span className="muted control-source">
                  Source: {latest[c.param] == null ? 'not recorded' : `${num(latest[c.param])}${c.unit ? ` ${c.unit}` : ''}`}
                </span>
                {fieldErrors[c.key] && <span className="field-error">{fieldErrors[c.key]}</span>}
              </label>
            ))}
          </div>

          <div className="actions">
            <button type="submit" disabled={running}>
              {running ? 'Simulating…' : 'Simulate scenario'}
            </button>
          </div>
        </form>
      )}

      {result && loaded && (
        <div className="scaleup-results">
          {stale && (
            <div className="alert alert-warning">Inputs changed since this result. Press “Simulate scenario” to update it.</div>
          )}
          <h3>
            Scenario estimate <span className="muted heading-note">{result.label}</span>
          </h3>

          <div className="scale-flow" aria-label="Scale-up flow">
            <div className="flow-box">
              <div className="muted small-label">Source</div>
              <div className="flow-value">{num(result.source.scale_liters)} L</div>
            </div>
            <div className="flow-arrow" aria-hidden="true">→</div>
            <div className="flow-box flow-factor">
              <div className="muted small-label">Scale factor</div>
              <div className="flow-value">{num(result.scale_factor, 2)}×</div>
            </div>
            <div className="flow-arrow" aria-hidden="true">→</div>
            <div className="flow-box">
              <div className="muted small-label">Target</div>
              <div className="flow-value">{num(result.target_scale_liters)} L</div>
            </div>
          </div>

          <div className="metrics">
            <MetricCard label="Scale factor" value={result.scale_factor} unit="×" digits={Number.isInteger(result.scale_factor) ? 0 : 2} />
            <MetricCard label="Volume increase" value={result.volume_increase_liters} unit="L" digits={Number.isInteger(result.volume_increase_liters) ? 0 : 2} />
            <MetricCard label="Target gas flow" value={result.gas_flow.target_l_per_min} unit="L/min" digits={2} />
            <MetricCard label="Target feed per litre" value={result.feed.target_ml_per_h_per_l} unit="mL/h per L" digits={3} />
          </div>

          <h3>Source vs target scenario</h3>
          <p className="muted small-note">
            Source values are the latest recorded value of each parameter. Cell density and culture duration are
            baselines carried over from the source, not predictions.
          </p>
          <ComparisonTable parameters={result.parameters} />

          <h3>Derived calculations</h3>
          <DerivedCalculations result={result} />

          <h3>Scenario summary</h3>
          <ul className="summary-list">
            {result.summary.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>

          <h3>Scale-Up Considerations</h3>
          <p className="muted small-note">
            Real scale-up needs engineering validation of factors this prototype does not calculate:
          </p>
          <ul className="considerations">
            {result.considerations.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <p className="muted small-note">{result.disclaimer}</p>
        </div>
      )}
      {loaded && <AdvancedScaleUpModeling experimentId={experimentId} targetScale={targetScale} />}
      <ScaleUpSeries active={active} dataVersion={dataVersion} onOpenComparison={onOpenComparison} />
    </section>
  )
}
