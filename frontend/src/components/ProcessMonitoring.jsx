import { useEffect, useState } from 'react'
import { getExperimentAnalysis } from '../api.js'
import ExperimentPicker from './ExperimentPicker.jsx'
import MetricCard from './MetricCard.jsx'
import ProcessStatistics from './ProcessStatistics.jsx'
import ProcessTrendCharts from './ProcessTrendCharts.jsx'
import SourceBadge from './SourceBadge.jsx'

const LATEST_VALUES = [
  { key: 'temperature_c', label: 'Temperature', unit: '°C', digits: 2 },
  { key: 'ph', label: 'pH', unit: '', digits: 2 },
  { key: 'dissolved_oxygen_percent', label: 'Dissolved Oxygen', unit: '% air sat.', digits: 1 },
  { key: 'agitation_rpm', label: 'Agitation', unit: 'rpm', digits: 0 },
  { key: 'cell_density', label: 'Cell Density', unit: '×10⁶ cells/mL', digits: 2 },
]

// Up to 2 decimals without trailing zeros, e.g. 96 h, 5.5 h, 0.25 h.
const hours = (h) => `${Number(h.toFixed(2))} h`

function DataQuality({ analysis }) {
  const q = analysis.data_quality
  return (
    <dl className="details quality">
      <dt>Observations</dt>
      <dd>{q.observation_count}</dd>
      <dt>Culture-time range</dt>
      <dd>
        {hours(analysis.culture_start_hours)} – {hours(analysis.culture_end_hours)}
      </dd>
      <dt>Distinct time points</dt>
      <dd>
        {q.distinct_time_points}
        {q.duplicate_time_points > 0 && ` (${q.duplicate_time_points} observation(s) share a time point)`}
      </dd>
      <dt>Interval between time points</dt>
      <dd>
        {q.smallest_interval_hours == null
          ? '—'
          : q.smallest_interval_hours === q.largest_interval_hours
            ? hours(q.smallest_interval_hours)
            : `${hours(q.smallest_interval_hours)} to ${hours(q.largest_interval_hours)}`}
      </dd>
      <dt>Optional values</dt>
      <dd>
        {q.missing_values.map((m) => (
          <div key={m.parameter}>
            {m.label}:{' '}
            {m.missing === 0
              ? 'recorded in all observations'
              : m.missing === q.observation_count
                ? 'not recorded'
                : `missing in ${m.missing} of ${q.observation_count}`}
          </div>
        ))}
      </dd>
      <dt>Trend charts</dt>
      <dd>{q.enough_for_trends ? 'Available (2 or more time points)' : 'Not available: at least 2 distinct time points are needed'}</dd>
    </dl>
  )
}

/** Descriptive monitoring view of one stored experiment: what was recorded, with no evaluation. */
export default function ProcessMonitoring({ active, dataVersion, analysisRequest }) {
  const [experiment, setExperiment] = useState(null)
  const [analysis, setAnalysis] = useState(null)
  const [error, setError] = useState(null)
  const [refreshCount, setRefreshCount] = useState(0)
  const experimentId = experiment?.experiment_id

  // "Analyze" from Experiment History selects that experiment here.
  useEffect(() => {
    if (analysisRequest) setExperiment({ experiment_id: analysisRequest.experimentId })
  }, [analysisRequest])

  useEffect(() => {
    if (!experimentId) {
      setAnalysis(null)
      setError(null)
      return
    }
    if (!active) return
    let cancelled = false
    getExperimentAnalysis(experimentId)
      .then((result) => {
        if (cancelled) return
        setAnalysis(result)
        setError(null)
      })
      .catch((err) => {
        if (cancelled) return
        setAnalysis(null)
        setError(`Could not load the analysis: ${err.message}`)
      })
    return () => {
      cancelled = true
    }
  }, [experimentId, active, dataVersion, refreshCount])

  const shown = analysis?.experiment.experiment_id === experimentId ? analysis : null
  const exp = shown?.experiment
  const latest = shown?.latest_observation

  return (
    <section className="card monitoring">
      <div className="card-header">
        <h2>Process Monitoring</h2>
        <button className="secondary small" onClick={() => setRefreshCount((n) => n + 1)} disabled={!experimentId}>
          Refresh
        </button>
      </div>
      <p className="muted disclaimer">
        Describes the observations stored for an experiment: what was recorded, over which culture times, and the
        range of each parameter. It does not assess process quality.
      </p>

      <ExperimentPicker
        sources={['manual', 'csv', 'simulated']}
        value={experiment}
        onChange={setExperiment}
        version={dataVersion}
        allowCreate={false}
      />

      {error && <div className="alert alert-error">{error}</div>}
      {!experimentId && <p className="muted placeholder">Select an experiment to see its process data.</p>}

      {shown && (
        <>
          <div className="exp-header">
            <div>
              <h3>{exp.name}</h3>
              <code>{exp.experiment_id}</code>
              {exp.description && <p className="muted exp-description">{exp.description}</p>}
            </div>
            <dl className="exp-facts">
              <div>
                <dt>Scale</dt>
                <dd>{exp.scale_liters} L</dd>
              </div>
              <div>
                <dt>Data source</dt>
                <dd>
                  <SourceBadge source={exp.data_source} />
                </dd>
              </div>
              <div>
                <dt>Observations</dt>
                <dd>{shown.observation_count}</dd>
              </div>
              <div>
                <dt>Culture duration</dt>
                <dd>{shown.culture_duration_hours == null ? '—' : hours(shown.culture_duration_hours)}</dd>
              </div>
            </dl>
          </div>
          {exp.data_source === 'simulated' && (
            <p className="muted small-note">
              Simulated observations are generated by software and are not laboratory measurements.
            </p>
          )}

          {shown.observation_count === 0 ? (
            <p className="muted placeholder">
              {shown.summary[0]} Add data on the Experiment Data page or save a simulator run to it.
            </p>
          ) : (
            <>
              <h3>Summary</h3>
              <ul className="summary-list">
                {shown.summary.map((sentence) => (
                  <li key={sentence}>{sentence}</li>
                ))}
              </ul>

              <h3>
                Latest values <span className="muted heading-note">at {hours(latest.culture_time_hours)} culture time</span>
              </h3>
              <div className="metrics">
                {LATEST_VALUES.map((m) => (
                  <MetricCard key={m.key} label={m.label} value={latest[m.key]} unit={m.unit} digits={m.digits} />
                ))}
              </div>

              <h3>Trends</h3>
              {shown.data_quality.enough_for_trends ? (
                active && <ProcessTrendCharts observations={shown.observations} parameters={shown.parameters} />
              ) : (
                <p className="muted placeholder">Trend charts need at least 2 distinct culture-time points.</p>
              )}

              <h3>Process statistics</h3>
              <ProcessStatistics parameters={shown.parameters} />

              <h3>Data coverage</h3>
              <DataQuality analysis={shown} />
            </>
          )}
        </>
      )}
    </section>
  )
}
