import { useEffect, useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { compareExperiments, getAIStatus, interpretComparison } from '../api.js'
import ExperimentPicker from './ExperimentPicker.jsx'
import SourceBadge from './SourceBadge.jsx'

const METRICS = [
  { id: 'average', label: 'Average' },
  { id: 'start', label: 'Start' },
  { id: 'final', label: 'Final' },
  { id: 'minimum', label: 'Min' },
  { id: 'maximum', label: 'Max' },
  { id: 'delta', label: 'Delta' },
]
const POINT_PARAMETERS = [
  { id: 'dissolved_oxygen_percent', label: 'Dissolved oxygen', unit: '% air sat.', digits: 1 },
  { id: 'cell_density', label: 'Cell density', unit: '×10⁶ cells/mL', digits: 2 },
  { id: 'temperature_c', label: 'Temperature', unit: '°C', digits: 2 },
  { id: 'ph', label: 'pH', unit: '', digits: 2 },
  { id: 'agitation_rpm', label: 'Agitation', unit: 'rpm', digits: 0 },
]
const AXIS_TICK = { fill: 'var(--muted)', fontSize: 12 }

const num = (v, d = 2) => v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
const signed = (v, d = 2) => (v > 0 ? '+' : '') + num(v, d)
const hours = (h) => (h == null ? '—' : `${Number(h.toFixed(2))} h`)
const withUnit = (text, unit) => (unit ? `${text} ${unit}` : text)

function SideCard({ letter, side }) {
  return (
    <div className="compare-card">
      <div className="muted small-label">Experiment {letter}</div>
      <div className="compare-card-title">
        <strong>{side.name}</strong> <SourceBadge source={side.data_source} />
      </div>
      <code>{side.experiment_id}</code>
      <dl className="compare-card-facts">
        <div>
          <dt>Scale</dt>
          <dd>{side.scale_liters} L</dd>
        </div>
        <div>
          <dt>Observations</dt>
          <dd>{side.observation_count}</dd>
        </div>
        <div>
          <dt>Duration</dt>
          <dd>{hours(side.duration_hours)}</dd>
        </div>
      </dl>
    </div>
  )
}

function DifferenceCell({ diff, digits, unit }) {
  if (diff.difference == null) return <td className="muted diff-note">{diff.note ?? 'Not available'}</td>
  return (
    <td className="num">
      {withUnit(signed(diff.difference, digits), unit)}
      {diff.percent_difference != null && <span className="muted"> ({signed(diff.percent_difference, 1)}%)</span>}
      {diff.note && <div className="muted diff-note">{diff.note}</div>}
    </td>
  )
}

function ParameterTable({ parameters }) {
  const [metric, setMetric] = useState('average')
  return (
    <>
      <div className="card-header section-header">
        <h3>Process parameters</h3>
        <div className="chip-group" aria-label="Statistic">
          {METRICS.map((m) => (
            <button type="button" key={m.id} className={`chip ${metric === m.id ? 'chip-active' : ''}`} onClick={() => setMetric(m.id)}>
              {m.label}
            </button>
          ))}
        </div>
      </div>
      <div className="table-wrap">
        <table className="compare-table">
          <thead>
            <tr>
              <th>Parameter</th>
              <th>Experiment A</th>
              <th>Experiment B</th>
              <th>Difference (B − A)</th>
            </tr>
          </thead>
          <tbody>
            {parameters.map((p) => {
              const diff = p.metrics[metric]
              const cell = (v, count) =>
                v == null ? <td className="muted">Not available</td> : <td className="num">{withUnit(num(v, p.decimals), p.unit)} <span className="muted">(n={count})</span></td>
              return (
                <tr key={p.parameter}>
                  <td>{p.label}</td>
                  {cell(diff.a, p.count_a)}
                  {cell(diff.b, p.count_b)}
                  <DifferenceCell diff={diff} digits={p.decimals} unit={p.unit} />
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="muted small-note">
        Difference = Experiment B − Experiment A. Percentages use |Experiment A| as the denominator and are omitted when A is
        zero or missing. Missing values are shown as “Not available”, never as zero.
      </p>
    </>
  )
}

function DataQualityTable({ dq, a, b }) {
  const missing = (q) =>
    q.missing_values
      .filter((m) => m.missing > 0)
      .map((m) => (m.missing === q.observation_count ? `${m.label}: not recorded` : `${m.label}: ${m.missing} of ${q.observation_count} missing`))
  const interval = (q) =>
    q.smallest_interval_hours == null ? '—' : q.smallest_interval_hours === q.largest_interval_hours ? hours(q.smallest_interval_hours) : `${hours(q.smallest_interval_hours)} to ${hours(q.largest_interval_hours)}`
  const rows = [
    ['Observations', dq.a.observation_count, dq.b.observation_count],
    ['Culture duration', hours(a.duration_hours), hours(b.duration_hours)],
    ['Culture-time range', a.culture_start_hours == null ? '—' : `${hours(a.culture_start_hours)} – ${hours(a.culture_end_hours)}`, b.culture_start_hours == null ? '—' : `${hours(b.culture_start_hours)} – ${hours(b.culture_end_hours)}`],
    ['Distinct time points', dq.a.distinct_time_points, dq.b.distinct_time_points],
    ['Repeated time points', dq.a.duplicate_time_points, dq.b.duplicate_time_points],
    ['Interval between time points', interval(dq.a), interval(dq.b)],
    ['Missing optional values', missing(dq.a).join('; ') || 'none', missing(dq.b).join('; ') || 'none'],
    ['Trend charts', dq.a.enough_for_trends ? 'available' : 'not available', dq.b.enough_for_trends ? 'available' : 'not available'],
  ]
  return (
    <div className="table-wrap">
      <table className="compare-table">
        <thead>
          <tr>
            <th>Data quality</th>
            <th>Experiment A</th>
            <th>Experiment B</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, va, vb]) => (
            <tr key={label}>
              <td>{label}</td>
              <td className="wrap">{va}</td>
              <td className="wrap">{vb}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TimeAlignment({ alignment, active }) {
  const [parameter, setParameter] = useState(POINT_PARAMETERS[0].id)
  const p = POINT_PARAMETERS.find((x) => x.id === parameter)
  const data = alignment.aligned_points
    .map((pt) => ({ t: pt.culture_time_hours, a: pt.values[parameter].a, b: pt.values[parameter].b }))
    .filter((d) => d.a != null && d.b != null)
  return (
    <>
      <p className="alignment-facts">
        <span>
          Shared time points: <strong>{alignment.common_time_points}</strong>
        </span>
        <span>
          Only in A: <strong>{alignment.only_a_time_points}</strong>
        </span>
        <span>
          Only in B: <strong>{alignment.only_b_time_points}</strong>
        </span>
        <span>
          Overlap: <strong>{alignment.overlap_start_hours == null ? '—' : `${hours(alignment.overlap_start_hours)} – ${hours(alignment.overlap_end_hours)}`}</strong>
        </span>
      </p>
      <p className="muted small-note">{alignment.note} No values are interpolated.</p>
      {data.length >= 2 && active && (
        <figure className="trend compare-chart">
          <figcaption className="card-header">
            <span>
              {p.label} at shared time points {p.unit && <span className="muted">({p.unit})</span>}
            </span>
            <select value={parameter} onChange={(e) => setParameter(e.target.value)} aria-label="Parameter">
              {POINT_PARAMETERS.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.label}
                </option>
              ))}
            </select>
          </figcaption>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--border)" />
              <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} allowDecimals={false} tick={AXIS_TICK} tickFormatter={(v) => `${Math.round(v)} h`} stroke="var(--border)" />
              <YAxis domain={['auto', 'auto']} tick={AXIS_TICK} width={56} stroke="var(--border)" tickFormatter={(v) => num(v, p.digits)} />
              <Tooltip
                formatter={(v, name) => [withUnit(num(v, p.digits), p.unit), name]}
                labelFormatter={(t) => `Culture time ${t} h`}
                contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6 }}
                labelStyle={{ color: 'var(--muted)' }}
                itemStyle={{ color: 'var(--text)' }}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} formatter={(value) => <span style={{ color: 'var(--text)' }}>{value}</span>} />
              <Line name="Experiment A" dataKey="a" stroke="var(--series)" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line name="Experiment B" dataKey="b" stroke="var(--series-b)" strokeWidth={2} strokeDasharray="6 3" dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
          {alignment.aligned_points_omitted > 0 && <p className="muted small-note">{alignment.aligned_points_omitted} further shared points not shown.</p>}
        </figure>
      )}
    </>
  )
}

function AnomalyColumn({ letter, side }) {
  const c = side.counts
  return (
    <div className="compare-anomalies">
      <h4>Experiment {letter}</h4>
      <p>
        <strong>{side.finding_count}</strong> finding(s): {c.significant} significant · {c.attention} attention · {c.info} info
      </p>
      {Object.keys(side.by_parameter).length > 0 && (
        <p className="muted small-note">By parameter: {Object.entries(side.by_parameter).map(([k, v]) => `${k} (${v})`).join(', ')}</p>
      )}
      <ul className="compare-findings">
        {side.findings.map((f) => (
          <li key={f.finding_id}>
            <span className={`sev-badge sev-${f.severity}`}>{f.severity.toUpperCase()}</span> {f.message}
          </li>
        ))}
      </ul>
      {side.findings_omitted > 0 && <p className="muted small-note">{side.findings_omitted} more finding(s) on the Anomalies page.</p>}
    </div>
  )
}

function Interpretation({ result }) {
  const i = result.interpretation
  const list = (title, items) => (
    <section className="copilot-section">
      <h4>{title}</h4>
      {items.length === 0 ? (
        <p className="muted">None stated.</p>
      ) : (
        <ul className="evidence-list">
          {items.map((x, n) => (
            <li key={n}>{x}</li>
          ))}
        </ul>
      )}
    </section>
  )
  return (
    <article className="copilot-reply">
      <section className="copilot-section">
        <h4>Overview</h4>
        <p className="copilot-answer">{i.overview}</p>
      </section>
      {list('Key differences', i.key_differences)}
      {list('Possible interpretations', i.possible_interpretations)}
      {list('Investigation points', i.investigation_points)}
      {list('Uncertainties', i.uncertainties)}
      <p className="muted small-note">
        {result.provider} · {result.model} · {new Date(result.generated_at).toLocaleTimeString()}. {result.notice}
      </p>
    </article>
  )
}

/** Deterministic side-by-side comparison of two stored experiments, with optional Gemini interpretation. */
export default function ExperimentComparison({ active, dataVersion }) {
  const [a, setA] = useState(null)
  const [b, setB] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const [configured, setConfigured] = useState(null)
  const [ai, setAI] = useState(null)
  const [aiError, setAIError] = useState(null)
  const [aiLoading, setAILoading] = useState(false)
  const aId = a?.experiment_id
  const bId = b?.experiment_id
  const same = Boolean(aId) && aId === bId
  const pairKey = `${aId}|${bId}`

  useEffect(() => {
    if (!active) return
    getAIStatus()
      .then((s) => setConfigured(s.configured))
      .catch(() => setConfigured(null))
  }, [active])

  const shown = result && result.key === pairKey ? result.data : null
  const shownAI = ai && ai.key === pairKey ? ai.data : null

  async function handleCompare() {
    setLoading(true)
    setError(null)
    setAIError(null)
    try {
      setResult({ key: pairKey, data: await compareExperiments(aId, bId) })
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleInterpret() {
    setAILoading(true)
    setAIError(null)
    try {
      setAI({ key: pairKey, data: await interpretComparison(aId, bId) })
    } catch (err) {
      if (err.status === 503 && /not configured/i.test(err.message)) setConfigured(false)
      setAIError(err.message)
    } finally {
      setAILoading(false)
    }
  }

  function swap() {
    setA(b)
    setB(a)
  }

  function clear() {
    setA(null)
    setB(null)
    setResult(null)
    setAI(null)
    setError(null)
    setAIError(null)
  }

  // Refresh a shown comparison when stored data changes elsewhere.
  useEffect(() => {
    if (active && shown) handleCompare()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataVersion])

  return (
    <section className="card comparison">
      <div className="card-header">
        <h2>Experiment Comparison</h2>
      </div>
      <p className="muted disclaimer">
        Compares two stored experiments using the application's own calculations (differences are B − A). It describes
        measurable differences only: there is no winner, ranking or score. Nothing is stored.
      </p>

      <div className="compare-pickers">
        <ExperimentPicker label="Experiment A" sources={['manual', 'csv', 'simulated']} value={a} onChange={setA} version={dataVersion} allowCreate={false} noneLabel="— Select Experiment A —" />
        <ExperimentPicker label="Experiment B" sources={['manual', 'csv', 'simulated']} value={b} onChange={setB} version={dataVersion} allowCreate={false} noneLabel="— Select Experiment B —" />
      </div>
      {same && <div className="alert alert-error">Select two different experiments to compare.</div>}
      <div className="actions">
        <button onClick={handleCompare} disabled={!aId || !bId || same || loading}>
          {loading ? 'Comparing…' : 'Compare Experiments'}
        </button>
        <button className="secondary" onClick={swap} disabled={!aId && !bId}>
          Swap A ↔ B
        </button>
        <button className="secondary" onClick={clear} disabled={!aId && !bId && !result}>
          Clear
        </button>
      </div>
      {error && <div className="alert alert-error">{error}</div>}

      {shown && (
        <div className="comparison-result">
          <div className="compare-cards">
            <SideCard letter="A" side={shown.experiment_a} />
            <SideCard letter="B" side={shown.experiment_b} />
          </div>
          {shown.notices.map((n) => (
            <div key={n} className="alert alert-warning compare-notice">
              {n}
            </div>
          ))}

          <h3>Scale</h3>
          <p className="scale-compare">
            {shown.scale.scale_a_liters ?? '—'} L (A) → {shown.scale.scale_b_liters ?? '—'} L (B):{' '}
            <strong>
              {shown.scale.scale_factor_b_over_a == null
                ? 'scale factor unavailable'
                : `scale factor B/A = ${Number(shown.scale.scale_factor_b_over_a.toFixed(3))}×`}
            </strong>
          </p>

          <h3>Summary</h3>
          <ul className="summary-list">
            {shown.summary.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>

          <ParameterTable parameters={shown.parameters} />

          <h3>Data quality</h3>
          <DataQualityTable dq={shown.data_quality} a={shown.experiment_a} b={shown.experiment_b} />

          <h3>Time alignment</h3>
          <TimeAlignment alignment={shown.time_alignment} active={active} />

          <h3>Anomaly findings</h3>
          <div className="compare-anomaly-grid">
            <AnomalyColumn letter="A" side={shown.anomalies.experiment_a} />
            <AnomalyColumn letter="B" side={shown.anomalies.experiment_b} />
          </div>

          <div className="card-header section-header">
            <h3>Gemini interpretation (optional)</h3>
            <span className={`treat-badge ${configured ? 'treat-preserved' : 'treat-na'}`} data-testid="ai-status">
              {configured == null ? 'Checking Gemini…' : configured ? 'Gemini configured' : 'Gemini not configured'}
            </span>
          </div>
          <p className="muted small-note">
            Gemini receives only the calculated comparison above (no raw observations) and interprets it. The comparison
            itself does not depend on Gemini.
          </p>
          {configured === false && (
            <div className="alert alert-error ai-not-configured">
              Gemini is not configured on the server (set <code>GEMINI_API_KEY</code>, see README). The deterministic
              comparison above is unaffected.
            </div>
          )}
          <div className="actions">
            <button onClick={handleInterpret} disabled={!configured || aiLoading}>
              {aiLoading ? 'Interpreting…' : 'Interpret with Gemini'}
            </button>
          </div>
          {aiLoading && (
            <div className="ai-loading" role="status">
              <span className="spinner" aria-hidden="true" /> Gemini is interpreting the comparison of {aId} and {bId}…
            </div>
          )}
          {aiError && <div className="alert alert-error">{aiError}</div>}
          {shownAI && !aiLoading && <Interpretation result={shownAI} />}
        </div>
      )}
      {!shown && !loading && aId && bId && !same && <p className="muted placeholder">Press “Compare Experiments”.</p>}
      {(!aId || !bId) && <p className="muted placeholder">Select Experiment A and Experiment B.</p>}
    </section>
  )
}
