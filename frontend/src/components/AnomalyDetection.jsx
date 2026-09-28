import { useEffect, useState } from 'react'
import { getExperimentAnomalies } from '../api.js'
import ExperimentPicker from './ExperimentPicker.jsx'
import FindingPrecedents from './FindingPrecedents.jsx'
import MetricCard from './MetricCard.jsx'
import SourceBadge from './SourceBadge.jsx'
import NextStep from './NextStep.jsx'

const SEVERITIES = [
  { id: 'significant', label: 'Significant' },
  { id: 'attention', label: 'Attention' },
  { id: 'info', label: 'Info' },
]

// Display decimals per parameter (formatting only), matching the Phase 5 analysis.
const DECIMALS = {
  temperature_c: 2,
  ph: 2,
  dissolved_oxygen_percent: 1,
  agitation_rpm: 0,
  cell_density: 2,
  feed_rate: 2,
  nutrient_concentration: 2,
  aeration_rate: 3,
}
const LABELS = {
  temperature_c: 'Temperature',
  ph: 'pH',
  dissolved_oxygen_percent: 'Dissolved oxygen',
  agitation_rpm: 'Agitation',
  cell_density: 'Cell density',
  feed_rate: 'Feed rate',
  nutrient_concentration: 'Nutrient concentration',
  aeration_rate: 'Aeration rate',
}
const MAX_POINTS_SHOWN = 20

const hours = (h) => `${Number(h.toFixed(2))} h`
const withUnit = (text, unit) => (unit ? `${text} ${unit}` : text)

function SeverityBadge({ severity }) {
  return <span className={`sev-badge sev-${severity}`}>{severity.toUpperCase()}</span>
}

function FindingItem({ finding: f, experimentId, onOpenComparison }) {
  const d = DECIMALS[f.parameter] ?? 2
  const value = (v) => withUnit(v.toFixed(d), f.unit)
  const signed = (v, digits = d) => (v > 0 ? '+' : '') + v.toFixed(digits)
  const time =
    f.previous_time_hours != null && f.previous_time_hours !== f.culture_time_hours
      ? `${hours(f.previous_time_hours)} – ${hours(f.culture_time_hours)}`
      : f.culture_time_hours != null
        ? hours(f.culture_time_hours)
        : '—'

  const rows = []
  if (f.parameter_label) rows.push(['Parameter', f.parameter_label])
  rows.push(['Culture time', time])
  if (f.observed_value != null) rows.push([f.type === 'range' ? 'Furthest value' : 'Observed value', value(f.observed_value)])
  if (f.previous_value != null) rows.push([f.type === 'trend' ? 'Start value' : 'Previous value', value(f.previous_value)])
  if (f.expected_min != null) rows.push(['Prototype monitoring range', `${f.expected_min} – ${withUnit(String(f.expected_max), f.unit)}`])
  if (f.threshold != null) {
    const t = f.threshold_kind === 'relative' ? `${Number((f.threshold * 100).toFixed(1))}%` : withUnit(String(f.threshold), f.unit)
    rows.push([f.type === 'trend' ? 'Minimum trend change' : 'Change threshold', `${t} (${f.threshold_kind}, prototype monitoring threshold)`])
  }
  if (f.absolute_change != null && f.type !== 'data_coverage') rows.push(['Absolute change', withUnit(signed(f.absolute_change), f.unit)])
  if (f.relative_change_percent != null) rows.push(['Relative change', `${signed(f.relative_change_percent, 1)}%`])
  if (f.direction) rows.push(['Direction', f.direction])
  if (f.related_parameters.length) rows.push(['Parameters', f.related_parameters.map((p) => LABELS[p] ?? p).join(', ')])

  return (
    <details className={`finding finding-${f.severity}`}>
      <summary>
        <SeverityBadge severity={f.severity} />
        <span className="finding-type">{f.type_label}</span>
        {f.parameter_label && <span className="finding-param">{f.parameter_label}</span>}
        <span className="finding-time muted">{time}</span>
        <span className="finding-message">{f.message}</span>
      </summary>
      <div className="finding-body">
        <dl className="details">
          {rows.map(([k, v]) => (
            <div key={k} className="detail-row">
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
        <h4>Evidence</h4>
        <ul className="evidence-list">
          {f.evidence.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        {f.points.length > 0 && (
          <div className="table-wrap">
            <table className="points-table">
              <caption>
                Observations involved ({f.points.length}
                {f.points.length > MAX_POINTS_SHOWN ? `, first ${MAX_POINTS_SHOWN} shown` : ''})
              </caption>
              <thead>
                <tr>
                  <th>Culture time</th>
                  <th>{withUnit(f.parameter_label ?? 'Value', f.unit ? `(${f.unit})` : '')}</th>
                </tr>
              </thead>
              <tbody>
                {f.points.slice(0, MAX_POINTS_SHOWN).map((p) => (
                  <tr key={`${p.culture_time_hours}-${p.value}`}>
                    <td className="num">{hours(p.culture_time_hours)}</td>
                    <td className="num">{p.value.toFixed(d)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <FindingPrecedents finding={f} experimentId={experimentId} stored onOpenComparison={onOpenComparison} />
      </div>
    </details>
  )
}

function MonitoringConfiguration({ config }) {
  return (
    <section className="config-section">
      <h3>Monitoring Configuration</h3>
      <p className="muted small-note">{config.note}</p>
      <div className="config-tables">
        <div className="table-wrap">
          <table>
            <caption>Prototype monitoring ranges</caption>
            <thead>
              <tr>
                <th>Parameter</th>
                <th>Min</th>
                <th>Max</th>
                <th>Significant if beyond by</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(config.ranges).map(([p, r]) => (
                <tr key={p}>
                  <td>{LABELS[p] ?? p}</td>
                  <td className="num">{r.min}</td>
                  <td className="num">{r.max}</td>
                  <td className="num">&gt; {r.severe_margin}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="table-wrap">
          <table>
            <caption>Sudden-change thresholds (between consecutive observations)</caption>
            <thead>
              <tr>
                <th>Parameter</th>
                <th>Threshold</th>
                <th>Type</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(config.changes).map(([p, c]) => (
                <tr key={p}>
                  <td>{LABELS[p] ?? p}</td>
                  <td className="num">&gt; {c.kind === 'relative' ? `${c.threshold * 100}%` : c.threshold}</td>
                  <td>{c.kind}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <ul className="evidence-list">
        <li>
          A change is <strong>significant</strong> when it exceeds {config.significant_change_multiplier}× its threshold;
          otherwise <strong>attention</strong>.
        </li>
        <li>
          A <strong>trend</strong> needs at least {config.trend_min_points} consecutive strictly increasing or decreasing
          readings with a total change of at least {config.trend_change_fraction}× the change threshold (info).
        </li>
        <li>
          Co-occurring changes: two or more rapid changes in the same interval (significant if two or more are
          significant).
        </li>
        <li>
          Data coverage (info): fewer than 2 time points, missing optional parameters, repeated time points, and gaps
          longer than {config.large_gap_factor}× the median interval.
        </li>
        <li>INFO, ATTENTION and SIGNIFICANT are display categories, not safety classifications.</li>
      </ul>
    </section>
  )
}

/** Deterministic, rule-based findings with evidence for a stored experiment (no AI, nothing stored). */
export default function AnomalyDetection({ active, dataVersion, onOpenComparison, onNavigate }) {
  const [experiment, setExperiment] = useState(null)
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const [refreshCount, setRefreshCount] = useState(0)
  const [filter, setFilter] = useState('all')
  const experimentId = experiment?.experiment_id

  useEffect(() => {
    if (!experimentId) {
      setReport(null)
      setError(null)
      return
    }
    if (!active) return
    let cancelled = false
    setLoading(true)
    getExperimentAnomalies(experimentId)
      .then((result) => {
        if (cancelled) return
        setReport(result)
        setError(null)
      })
      .catch((err) => {
        if (cancelled) return
        setReport(null)
        setError(`Could not run the checks: ${err.message}`)
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [experimentId, active, dataVersion, refreshCount])

  const shown = report?.experiment_id === experimentId ? report : null
  const visible = shown?.findings.filter((f) => filter === 'all' || f.severity === filter) ?? []

  return (
    <section className="card anomalies">
      <div className="card-header">
        <h2>Anomalies</h2>
        <button className="secondary small" onClick={() => setRefreshCount((n) => n + 1)} disabled={!experimentId || loading}>
          {loading ? 'Checking…' : 'Re-run checks'}
        </button>
      </div>
      <p className="muted disclaimer">
        Deterministic, rule-based checks on the stored observations: prototype monitoring ranges, rapid changes,
        persistent trends, co-occurring changes and data coverage. Each finding shows its evidence. Findings describe
        the data; they are not diagnoses or safety decisions.
      </p>

      <ExperimentPicker
        sources={['manual', 'csv', 'simulated']}
        value={experiment}
        onChange={(e) => {
          setExperiment(e)
          setFilter('all')
        }}
        version={dataVersion}
        allowCreate={false}
      />
      {error && <div className="alert alert-error">{error}</div>}
      {!experimentId && <p className="muted placeholder">Select an experiment to run the checks.</p>}

      {shown && (
        <>
          <div className="anomaly-header">
            <span>
              <strong>{shown.experiment.name}</strong> <SourceBadge source={shown.experiment.data_source} />
            </span>
            <span className="muted">
              {shown.observation_count} observation(s) · {shown.finding_count} finding(s)
            </span>
          </div>

          <div className="metrics">
            {SEVERITIES.map((s) => (
              <MetricCard key={s.id} label={s.label} value={shown.counts[s.id]} digits={0} className={`metric-sev metric-${s.id}`} />
            ))}
          </div>

          <h3>Summary</h3>
          <ul className="summary-list">
            {shown.summary.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>

          <div className="card-header findings-header">
            <h3>Process Findings</h3>
            {shown.finding_count > 0 && (
              <div className="chip-group" aria-label="Filter by severity">
                {[{ id: 'all', label: 'All' }, ...SEVERITIES].map((s) => (
                  <button
                    type="button"
                    key={s.id}
                    className={`chip ${filter === s.id ? 'chip-active' : ''}`}
                    onClick={() => setFilter(s.id)}
                  >
                    {s.label} ({s.id === 'all' ? shown.finding_count : shown.counts[s.id]})
                  </button>
                ))}
              </div>
            )}
          </div>
          {shown.observation_count === 0 ? (
            <p className="muted placeholder">No observations recorded yet, so there is nothing to check.</p>
          ) : shown.finding_count === 0 ? (
            <p className="muted placeholder">
              No findings with the prototype monitoring configuration. This does not certify the process; it means no
              configured rule was triggered.
            </p>
          ) : visible.length === 0 ? (
            <p className="muted placeholder">No findings with this severity.</p>
          ) : (
            <div className="findings">
              {visible.map((f) => (
                <FindingItem key={`${experimentId}|${f.finding_id}`} finding={f} experimentId={experimentId} onOpenComparison={onOpenComparison} />
              ))}
            </div>
          )}

          <MonitoringConfiguration config={shown.configuration} />
        </>
      )}
      <NextStep stage="Compare" label="Compare Runs" page="comparison" hint="Use Find precedents on a finding first, or compare any two stored runs." onNavigate={onNavigate} />
    </section>
  )
}
