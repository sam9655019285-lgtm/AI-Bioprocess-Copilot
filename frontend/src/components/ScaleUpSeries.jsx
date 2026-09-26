import { useEffect, useState } from 'react'
import { compareExperiments, interpretComparison, modelScaleUp } from '../api.js'
import { Interpretation } from './ExperimentComparison.jsx'
import ExperimentPicker from './ExperimentPicker.jsx'
import SourceBadge from './SourceBadge.jsx'

/*
 * Stored Scale-Up Series (Phase 20): two STORED runs at (possibly) different scales, side by side.
 * Everything shown comes from existing deterministic endpoints - the experiment comparison
 * (target − source) and the advanced scale-up model evaluated at each run's own observed
 * conditions (no geometry is assumed). Gemini is used only on "Explain with AI" (existing
 * comparison interpretation). It does not judge scale-up success or predict outcomes.
 */

const METRICS = [
  { id: 'average', label: 'Average' },
  { id: 'final', label: 'Final' },
  { id: 'minimum', label: 'Min' },
  { id: 'maximum', label: 'Max' },
]
const ENGINEERING = [
  ['rpm', 'Agitation'],
  ['vvm', 'Aeration'],
  ['power_per_volume_w_m3', 'Power per volume (P/V)'],
  ['tip_speed_m_s', 'Impeller tip speed'],
  ['kla_per_h', 'kLa (estimated)'],
  ['otr_mmol_l_h', 'OTR'],
  ['our_mmol_l_h', 'OUR'],
]
const CATEGORY_CLASS = {
  'OBSERVED DATA': 'cat-observed',
  'DERIVED CALCULATION': 'cat-derived',
  'MODEL ASSUMPTION': 'cat-assumption',
  'SCENARIO ASSUMPTION': 'cat-assumption',
  'SCENARIO RESULT': 'cat-scenario',
  'AI INTERPRETATION': 'cat-ai',
  'NOT AVAILABLE': 'cat-na',
}
const SHARED_POINTS_SHOWN = 12
const ALIGNED_PARAMS = [
  ['cell_density', 'Cell density'],
  ['dissolved_oxygen_percent', 'DO'],
]

const num = (v, d = 3) => (v == null ? 'Not available' : v.toLocaleString('en-US', { maximumFractionDigits: d }))
const withUnit = (v, unit, d) => (v == null ? 'Not available' : unit && unit !== '-' ? `${num(v, d)} ${unit}` : num(v, d))
const signed = (v, d = 3) => (v == null ? '—' : `${v > 0 ? '+' : ''}${num(v, d)}`)

function Badge({ category }) {
  return <span className={`cat-badge ${CATEGORY_CLASS[category] ?? ''}`}>{category}</span>
}

function SideCard({ title, side }) {
  return (
    <div className="series-side" data-testid={`series-${title.toLowerCase()}`}>
      <div className="muted small-label">{title}</div>
      <strong>{side.experiment_id}</strong> <SourceBadge source={side.data_source} />
      <div className="muted">{side.name}</div>
      <div>
        {num(side.scale_liters)} L · {side.observation_count} observation(s)
      </div>
    </div>
  )
}

function ScaleDiagram({ scale }) {
  const f = scale.scale_factor_b_over_a
  const arrow = scale.same_scale ? '↔' : '↓'
  return (
    <div className="series-diagram" data-testid="series-diagram" aria-label="Scale relationship">
      <span className="series-vol">{num(scale.scale_a_liters)} L</span>
      <span className="series-arrow">
        {arrow}
        {f != null && !scale.same_scale && <span className="series-factor"> {num(f, 3)}×</span>}
      </span>
      <span className="series-vol">{num(scale.scale_b_liters)} L</span>
    </div>
  )
}

function relationText(scale) {
  const f = scale.scale_factor_b_over_a
  if (f == null) return 'Scale relationship not available (a scale is missing).'
  if (scale.same_scale) return 'Target and source are at the same scale.'
  return f > 1 ? `Target scale is ${num(f, 3)}× the source scale.` : `Target scale is smaller than the source scale (${num(f, 3)}×).`
}

export default function ScaleUpSeries({ active, dataVersion, onOpenComparison }) {
  const [source, setSource] = useState(null)
  const [target, setTarget] = useState(null)
  const [data, setData] = useState(null) // { key, comparison, engineering: { source, target } }
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const [metric, setMetric] = useState('average')
  const [ai, setAI] = useState(null)
  const [aiError, setAIError] = useState(null)
  const [aiLoading, setAILoading] = useState(false)
  const sId = source?.experiment_id
  const tId = target?.experiment_id
  const same = Boolean(sId) && sId === tId
  const key = `${sId}|${tId}`

  // Deterministic requests only; run when both runs are chosen and this page is open.
  useEffect(() => {
    if (!sId || !tId || same || !active) return
    let cancelled = false
    setLoading(true)
    setError(null)
    compareExperiments(sId, tId)
      .then(async (comparison) => {
        // Each run's own observed conditions at its own scale; no geometry and default model constants.
        const [es, et] = await Promise.all([
          modelScaleUp({ source_experiment_id: sId, target_scale_liters: comparison.experiment_a.scale_liters }),
          modelScaleUp({ source_experiment_id: tId, target_scale_liters: comparison.experiment_b.scale_liters }),
        ])
        if (!cancelled) setData({ key, comparison, engineering: { source: es, target: et } })
      })
      .catch((err) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sId, tId, same, active, dataVersion])

  useEffect(() => {
    setAI(null)
    setAIError(null)
  }, [key])

  async function explain() {
    setAILoading(true)
    setAIError(null)
    try {
      setAI({ key, data: await interpretComparison(sId, tId) })
    } catch (err) {
      setAIError(err.message)
    } finally {
      setAILoading(false)
    }
  }

  const shown = data?.key === key ? data : null
  const c = shown?.comparison
  const eng = shown?.engineering
  const shownAI = ai?.key === key ? ai.data : null

  const caveats = []
  if (c) {
    if ([c.experiment_a, c.experiment_b].some((s) => s.data_source === 'simulated')) {
      caveats.push('At least one run is SIMULATED (software-generated, not laboratory measurements); the simulator does not model physical scale effects.')
    }
    if (c.data_quality.observation_count_difference) caveats.push(`Observation counts differ (${c.experiment_a.observation_count} vs ${c.experiment_b.observation_count}).`)
    if (c.data_quality.duration_difference_hours) caveats.push(`Observed culture durations differ by ${num(Math.abs(c.data_quality.duration_difference_hours), 2)} h.`)
    const partial = c.parameters.filter((p) => p.availability !== 'both' && p.availability !== 'neither').map((p) => p.label)
    if (partial.length) caveats.push(`Recorded in only one run: ${partial.join(', ')}.`)
    if (c.time_alignment.common_time_points < 2) caveats.push('Insufficient shared time points for time-aligned comparison.')
    const geometryMissing = eng && eng.source.source.power_per_volume_w_m3.value == null
    if (geometryMissing) caveats.push('Geometry-dependent engineering values (P/V, tip speed, kLa, OTR) are not available: no impeller diameter is stored.')
    caveats.push(...c.notices)
  }

  return (
    <section className="series" data-testid="scaleup-series">
      <div className="card-header">
        <h3>Stored Scale-Up Series</h3>
        <span className="cat-badge cat-observed">OBSERVED DATA</span>
      </div>
      <p className="muted small-note">
        Compares two stored runs across scales using the existing experiment comparison (target − source) and engineering
        calculations. It reports observed differences and deterministic values only; it does not assess whether a scale-up
        succeeded or predict biological outcomes.
      </p>
      <div className="compare-pickers">
        <ExperimentPicker label="Source (smaller or reference) run" sources={['manual', 'csv', 'simulated']} value={source} onChange={setSource} version={dataVersion} allowCreate={false} noneLabel="— Select source run —" />
        <ExperimentPicker label="Target run" sources={['manual', 'csv', 'simulated']} value={target} onChange={setTarget} version={dataVersion} allowCreate={false} noneLabel="— Select target run —" />
      </div>
      {same && <div className="alert alert-error">Select two different experiments.</div>}
      {(!sId || !tId) && <p className="muted placeholder">Select a source run and a target run.</p>}
      {loading && <p className="muted">Loading…</p>}
      {error && <div className="alert alert-error">{error}</div>}

      {c && (
        <>
          <div className="series-top">
            <SideCard title="Source" side={c.experiment_a} />
            <div className="series-relation">
              <ScaleDiagram scale={c.scale} />
              <p data-testid="series-relation">{relationText(c.scale)}</p>
              <p className="muted small-note">
                Volume change: {signed(c.scale.scale_b_liters - c.scale.scale_a_liters, 3)} L <Badge category="DERIVED CALCULATION" />
              </p>
            </div>
            <SideCard title="Target" side={c.experiment_b} />
          </div>

          <h4>Culture time</h4>
          <table className="plan-table series-duration">
            <tbody>
              <tr>
                <td>Source observed duration</td>
                <td className="num">{withUnit(c.experiment_a.duration_hours, 'h', 2)}</td>
              </tr>
              <tr>
                <td>Target observed duration</td>
                <td className="num">{withUnit(c.experiment_b.duration_hours, 'h', 2)}</td>
              </tr>
              <tr>
                <td>Difference (target − source)</td>
                <td className="num">{c.data_quality.duration_difference_hours == null ? 'Not available' : `${signed(c.data_quality.duration_difference_hours, 2)} h`}</td>
              </tr>
            </tbody>
          </table>

          <div className="card-header">
            <h4>Observed process parameters</h4>
            <div className="chip-group" aria-label="Metric">
              {METRICS.map((m) => (
                <button key={m.id} type="button" className={`chip ${metric === m.id ? 'chip-active' : ''}`} onClick={() => setMetric(m.id)}>
                  {m.label}
                </button>
              ))}
            </div>
          </div>
          <p className="prec-legend">
            Values <Badge category="OBSERVED DATA" /> · difference and % <Badge category="DERIVED CALCULATION" /> (target − source; % relative to source). Not ranked.
          </p>
          <div className="table-wrap">
            <table className="comparison-table" data-testid="series-parameters">
              <thead>
                <tr>
                  <th>Parameter</th>
                  <th>Source</th>
                  <th>Target</th>
                  <th>Difference</th>
                  <th>%</th>
                </tr>
              </thead>
              <tbody>
                {c.parameters.map((p) => {
                  const m = p.metrics[metric]
                  return (
                    <tr key={p.parameter}>
                      <td>{p.label}</td>
                      <td className="num">{withUnit(m?.a, p.unit, p.decimals)}</td>
                      <td className="num">{withUnit(m?.b, p.unit, p.decimals)}</td>
                      <td className="num">{signed(m?.difference, p.decimals)}</td>
                      <td className="num">{m?.percent_difference == null ? '—' : `${signed(m.percent_difference, 1)}%`}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <h4>Engineering context at each run&apos;s observed conditions</h4>
          <p className="muted small-note">
            From the existing Advanced Scale-Up Modeling, evaluated at each run&apos;s latest observed agitation, aeration and cell density.
            No impeller geometry is assumed; values that need it are <Badge category="NOT AVAILABLE" />. Default model constants apply{' '}
            <Badge category="SCENARIO ASSUMPTION" /> — set scenario assumptions in Advanced Scale-Up Modeling above.
          </p>
          {eng && (
            <div className="table-wrap">
              <table className="comparison-table" data-testid="series-engineering">
                <thead>
                  <tr>
                    <th>Quantity</th>
                    <th>Source ({num(c.experiment_a.scale_liters)} L)</th>
                    <th>Target ({num(c.experiment_b.scale_liters)} L)</th>
                  </tr>
                </thead>
                <tbody>
                  {ENGINEERING.map(([k, label]) => {
                    const qs = eng.source.source[k]
                    const qt = eng.target.source[k]
                    return (
                      <tr key={k}>
                        <td>{label}</td>
                        {[qs, qt].map((q, i) => (
                          <td key={i} className="num">
                            {withUnit(q.value, q.unit, 4)} <Badge category={q.value == null ? 'NOT AVAILABLE' : q.category} />
                          </td>
                        ))}
                      </tr>
                    )
                  })}
                  <tr>
                    <td>Oxygen balance (OTR − OUR)</td>
                    {[eng.source.oxygen_balance_source, eng.target.oxygen_balance_source].map((b, i) => (
                      <td key={i} className="num">
                        {b.difference_mmol_l_h == null ? 'Not available' : `${signed(b.difference_mmol_l_h, 3)} mmol/L/h · ${b.state}`}{' '}
                        <Badge category={b.difference_mmol_l_h == null ? 'NOT AVAILABLE' : b.category} />
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          )}

          <h4>Time-aligned comparison</h4>
          {c.time_alignment.common_time_points < 2 ? (
            <p className="alert alert-warning" data-testid="series-alignment">
              Insufficient shared time points for time-aligned comparison.
            </p>
          ) : (
            <div data-testid="series-alignment">
              <p className="muted small-note">
                {c.time_alignment.common_time_points} shared culture-time points ({num(c.time_alignment.overlap_start_hours, 2)}–
                {num(c.time_alignment.overlap_end_hours, 2)} h); values are compared only where both runs have an observation (no
                interpolation). {c.time_alignment.note}
              </p>
              <div className="table-wrap">
                <table className="comparison-table">
                  <thead>
                    <tr>
                      <th>Culture time</th>
                      {ALIGNED_PARAMS.map(([p, l]) => (
                        <th key={p}>{l}: source / target</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {c.time_alignment.aligned_points.slice(0, SHARED_POINTS_SHOWN).map((pt) => (
                      <tr key={pt.culture_time_hours}>
                        <td className="num">{num(pt.culture_time_hours, 2)} h</td>
                        {ALIGNED_PARAMS.map(([p]) => {
                          const v = pt.values[p]
                          return (
                            <td key={p} className="num">
                              {v ? `${num(v.a)} / ${num(v.b)}` : 'Not available'}
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {c.time_alignment.aligned_points.length > SHARED_POINTS_SHOWN && (
                <p className="muted small-note">First {SHARED_POINTS_SHOWN} shared points shown; the full comparison has the chart.</p>
              )}
            </div>
          )}

          <h4>Data quality and caveats</h4>
          <ul className="series-caveats" data-testid="series-caveats">
            {caveats.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>

          <div className="fc-actions">
            <button type="button" className="secondary" onClick={() => onOpenComparison?.(sId, tId)} disabled={!onOpenComparison}>
              Open Full Comparison
            </button>
            <button type="button" className="secondary" onClick={explain} disabled={aiLoading}>
              {aiLoading ? 'Asking Gemini…' : 'Explain with AI'}
            </button>
          </div>
          {aiError && <div className="alert alert-error">{aiError}</div>}
          {shownAI && (
            <div className="series-ai" data-testid="series-ai">
              <Badge category="AI INTERPRETATION" /> <span className="muted small-note">Differences are target − source.</span>
              <Interpretation result={shownAI} />
            </div>
          )}
        </>
      )}
    </section>
  )
}
