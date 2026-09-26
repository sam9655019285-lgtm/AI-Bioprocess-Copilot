import { useEffect, useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { forecastExperiment } from '../api.js'
import ExperimentPicker from './ExperimentPicker.jsx'

/*
 * Process Forecasting (Phase 15): an Illustrative Process Forecast computed by the backend
 * (POST /api/experiments/{id}/forecast) from stored observations and configurable
 * assumptions. This component only collects settings and displays labelled results;
 * it never calls Gemini.
 */

const BANNER =
  'Forecasts are model-based estimates using historical observations and configurable assumptions. They are not validated biological predictions.'
const CATEGORY_CLASS = {
  'OBSERVED DATA': 'cat-observed',
  'DERIVED CALCULATION': 'cat-derived',
  'MODEL ASSUMPTION': 'cat-assumption',
  'MODEL FORECAST': 'cat-forecast',
  'SCENARIO INPUT': 'cat-assumption',
  'SCENARIO RESULT': 'cat-scenario',
  'NOT AVAILABLE': 'cat-na',
}
const WHAT_IF = [
  { key: 'horizon_hours', label: 'Forecast horizon', unit: 'h' },
  { key: 'target_scale_liters', label: 'Target scale', unit: 'L' },
  { key: 'temperature_c', label: 'Temperature', unit: '°C' },
  { key: 'ph', label: 'pH', unit: '' },
  { key: 'dissolved_oxygen_percent', label: 'DO', unit: '% air sat.' },
  { key: 'agitation_rpm', label: 'Agitation', unit: 'rpm' },
  { key: 'aeration_rate', label: 'Aeration', unit: 'vvm' },
  { key: 'feed_rate', label: 'Feed rate', unit: 'mL/h' },
]
const EMPTY_WHAT_IF = Object.fromEntries(WHAT_IF.map((f) => [f.key, '']))
const AXIS_TICK = { fill: 'var(--muted)', fontSize: 12 }

const num = (v, d = 4) => v.toLocaleString('en-US', { maximumSignificantDigits: d })
const withUnit = (text, unit) => (unit ? `${text} ${unit}` : text)

function Badge({ category }) {
  return <span className={`cat-badge ${CATEGORY_CLASS[category] ?? ''}`}>{category}</span>
}

function ValueCard({ testid, title, point, unit, category }) {
  return (
    <div className="metric adv-card" data-testid={testid}>
      <div className="metric-label">{title}</div>
      <div className="metric-value">{point ? withUnit(num(point.value), unit) : 'Not available'}</div>
      <div className="metric-caption">{point ? `at ${num(point.culture_time_hours)} h` : ' '}</div>
      <Badge category={point ? category : 'NOT AVAILABLE'} />
    </div>
  )
}

function ForecastChart({ p }) {
  const data = [
    ...p.observed.map((o) => ({ t: o.culture_time_hours, observed: o.value })),
    // The forecast line starts at the last observation so the two lines join.
    { t: p.current.culture_time_hours, forecast: p.current.value },
    ...p.forecast.map((o) => ({ t: o.culture_time_hours, forecast: o.value })),
  ]
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid vertical={false} stroke="var(--border)" />
        <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} tick={AXIS_TICK} tickFormatter={(v) => `${Math.round(v)} h`} stroke="var(--border)" />
        <YAxis domain={['auto', 'auto']} tick={AXIS_TICK} width={56} stroke="var(--border)" tickFormatter={(v) => num(v, 3)} />
        <Tooltip
          formatter={(v, name) => [withUnit(num(v), p.unit), name]}
          labelFormatter={(t) => `Culture time ${num(t)} h`}
          contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6 }}
          labelStyle={{ color: 'var(--muted)' }}
          itemStyle={{ color: 'var(--text)' }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} formatter={(value) => <span style={{ color: 'var(--text)' }}>{value}</span>} />
        <ReferenceLine x={p.current.culture_time_hours} stroke="var(--muted)" strokeDasharray="3 3" label={{ value: 'Forecast start', fill: 'var(--muted)', fontSize: 11, position: 'insideTopLeft' }} />
        <Line name="Observed data" dataKey="observed" stroke="var(--series)" strokeWidth={2} dot={{ r: 2 }} connectNulls isAnimationActive={false} />
        <Line name="Model forecast" dataKey="forecast" stroke="var(--series-b)" strokeWidth={2} strokeDasharray="6 3" dot={false} connectNulls isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}

function ParameterPanel({ p }) {
  const available = p.status === 'available'
  return (
    <figure className="trend forecast-param" data-testid={`fc-${p.parameter}`}>
      <figcaption className="card-header">
        <span>
          {p.label} {p.unit && <span className="muted">({p.unit})</span>}
        </span>
        <span className="muted small-note">{available ? p.model_label : ''}</span>
      </figcaption>
      <div className="grid adv-cards">
        <ValueCard testid={`fc-${p.parameter}-current`} title="Current (last observed)" point={p.current} unit={p.unit} category="OBSERVED DATA" />
        <ValueCard testid={`fc-${p.parameter}-end`} title="Forecast at horizon end" point={available ? p.forecast_end : null} unit={p.unit} category={p.category} />
      </div>
      {available ? (
        <ForecastChart p={p} />
      ) : (
        <p className={`alert ${p.status === 'invalid_assumption' ? 'alert-error' : 'alert-warning'} fc-message`}>{p.message}</p>
      )}
      {available && (
        <details className="fc-assumptions">
          <summary>Model assumptions</summary>
          <p>
            <Badge category="MODEL ASSUMPTION" /> <code>{p.equation}</code>
          </p>
          <ul>
            {Object.entries(p.model_parameters).map(([k, v]) => (
              <li key={k}>
                {k} = {num(v)} <span className="muted">(fitted from {p.observation_count} observations{k === 'K' ? '; assumed' : ''})</span>
              </li>
            ))}
            {p.assumptions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
          <div className="muted small-label">Limitations</div>
          <ul>
            {p.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </details>
      )}
    </figure>
  )
}

export default function ProcessForecasting({ dataVersion, onForecastSettings }) {
  const [experiment, setExperiment] = useState(null)
  const [horizon, setHorizon] = useState('')
  const [cellModel, setCellModel] = useState('exponential')
  const [capacity, setCapacity] = useState('')
  const [whatIf, setWhatIf] = useState(EMPTY_WHAT_IF)
  const [scenario, setScenario] = useState(null) // applied what-if inputs (null = none)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const experimentId = experiment?.experiment_id

  useEffect(() => {
    if (!experimentId) return
    const body = { cell_model: cellModel }
    if (horizon.trim() !== '') body.horizon_hours = Number(horizon)
    if (cellModel === 'logistic' && capacity.trim() !== '') body.carrying_capacity = Number(capacity)
    if (scenario) body.scenario = scenario
    let cancelled = false
    const timer = setTimeout(() => {
      setLoading(true)
      forecastExperiment(experimentId, body)
        .then((r) => {
          if (cancelled) return
          setResult(r)
          setError(null)
          onForecastSettings?.(experimentId, body)
        })
        .catch((err) => !cancelled && setError(err.message))
        .finally(() => !cancelled && setLoading(false))
    }, 300)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [experimentId, horizon, cellModel, capacity, scenario, dataVersion, onForecastSettings])

  function selectExperiment(e) {
    setExperiment(e)
    setResult(null)
    setScenario(null)
    setWhatIf(EMPTY_WHAT_IF)
  }

  function applyWhatIf(e) {
    e.preventDefault()
    const s = {}
    for (const f of WHAT_IF) if (whatIf[f.key].trim() !== '') s[f.key] = Number(whatIf[f.key])
    setScenario(Object.keys(s).length ? s : null)
  }

  const r = result?.experiment_id === experimentId ? result : null

  return (
    <section className="card forecasting">
      <div className="card-header">
        <h2>Illustrative Process Forecast</h2>
        <span className="cat-badge cat-forecast">MODEL FORECAST</span>
      </div>
      <p className="alert alert-warning fc-banner">{BANNER}</p>
      <p className="muted small-note">Model forecast based on available observations and configurable assumptions.</p>

      <ExperimentPicker
        sources={['manual', 'csv', 'simulated']}
        value={experiment}
        onChange={selectExperiment}
        version={dataVersion}
        allowCreate={false}
        noneLabel="— Select an experiment —"
      />
      {!experimentId && <p className="muted placeholder">Select a stored experiment to forecast.</p>}

      {experimentId && (
        <div className="fc-controls">
          <label>
            Forecast horizon (h)
            <input name="fc-horizon" type="number" min="0" step="any" value={horizon} placeholder="default: 25% of span" onChange={(e) => setHorizon(e.target.value)} />
          </label>
          <label>
            Cell density model
            <select name="fc-model" value={cellModel} onChange={(e) => setCellModel(e.target.value)}>
              <option value="exponential">Exponential</option>
              <option value="logistic">Logistic</option>
            </select>
          </label>
          {cellModel === 'logistic' && (
            <label>
              Carrying capacity K <Badge category="MODEL ASSUMPTION" />
              <input name="fc-k" type="number" min="0" step="any" value={capacity} placeholder="default: 2 × observed max" onChange={(e) => setCapacity(e.target.value)} />
            </label>
          )}
          {loading && <span className="muted">Calculating…</span>}
        </div>
      )}
      {error && <div className="alert alert-error">{error}</div>}

      {r && (
        <>
          <p className="muted small-note" data-testid="fc-horizon">
            Horizon: {r.horizon_hours == null ? 'Not available' : `${num(r.horizon_hours)} h`}
            {r.horizon_note && ` — ${r.horizon_note}`}
          </p>
          <div className="fc-params">
            {r.parameters.map((p) => (
              <ParameterPanel key={p.parameter} p={p} />
            ))}
          </div>
        </>
      )}

      {experimentId && (
        <form className="fc-whatif" onSubmit={applyWhatIf} noValidate>
          <h3>What-if scenario</h3>
          <p className="muted small-note">
            <Badge category="SCENARIO INPUT" /> values are recorded with the scenario. Only the horizon changes the forecast; no
            biological effect of temperature, pH, DO, agitation, aeration, feed or scale is modelled.
          </p>
          <div className="fc-controls">
            {WHAT_IF.map((f) => (
              <label key={f.key}>
                {f.label} {f.unit && <span className="muted">({f.unit})</span>}
                <input name={`fc-wi-${f.key}`} type="number" step="any" value={whatIf[f.key]} onChange={(e) => setWhatIf({ ...whatIf, [f.key]: e.target.value })} />
              </label>
            ))}
          </div>
          <div className="fc-actions">
            <button type="submit">Apply scenario</button>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setWhatIf(EMPTY_WHAT_IF)
                setScenario(null)
              }}
            >
              Clear scenario
            </button>
          </div>
          {r && r.scenario_inputs.length > 0 && (
            <div className="table-wrap">
              <table className="fc-scenario-table" data-testid="fc-scenario-inputs">
                <thead>
                  <tr>
                    <th>Input</th>
                    <th>Value</th>
                    <th>Label</th>
                    <th>Effect on forecast</th>
                  </tr>
                </thead>
                <tbody>
                  {r.scenario_inputs.map((s) => (
                    <tr key={s.name}>
                      <td>{s.name}</td>
                      <td className="num">{withUnit(num(s.value), s.unit)}</td>
                      <td>
                        <Badge category={s.category} />
                      </td>
                      <td className="wrap">{s.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted small-note">
                Forecast values above are labelled <Badge category="SCENARIO RESULT" /> while a scenario horizon is applied.
              </p>
            </div>
          )}
        </form>
      )}
    </section>
  )
}
