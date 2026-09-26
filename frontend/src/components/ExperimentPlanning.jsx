import { useState } from 'react'
import { interpretPlan, planExperiment } from '../api.js'
import ExperimentPicker from './ExperimentPicker.jsx'

/*
 * Experiment Planning (Phase 16): "What should I test next?". The backend generates
 * candidate conditions with deterministic design rules (POST /api/experiments/{id}/plan);
 * this component only collects constraints and displays labelled results. Gemini is
 * called only when the user clicks "Explain with AI". Nothing is applied or saved.
 */

const OBJECTIVES = [
  { id: 'improve_cell_density', label: 'Explore conditions related to cell density' },
  { id: 'maintain_stability', label: 'Maintain process stability' },
  { id: 'explore_conditions', label: 'Explore operating conditions' },
  { id: 'compare_candidates', label: 'Compare candidate conditions' },
]
const PARAMETERS = [
  { key: 'temperature_c', label: 'Temperature', unit: '°C' },
  { key: 'ph', label: 'pH', unit: '' },
  { key: 'dissolved_oxygen_percent', label: 'Dissolved oxygen', unit: '% air sat.' },
  { key: 'agitation_rpm', label: 'Agitation', unit: 'rpm' },
  { key: 'aeration_rate', label: 'Aeration', unit: 'vvm' },
  { key: 'feed_rate', label: 'Feed rate', unit: 'mL/h' },
]
const EMPTY_ROWS = Object.fromEntries(PARAMETERS.map((p) => [p.key, { min: '', max: '', step: '', changeable: true }]))
const CATEGORY_CLASS = {
  'OBSERVED DATA': 'cat-observed',
  'DERIVED CALCULATION': 'cat-derived',
  'USER CONSTRAINT': 'cat-user',
  'PLANNING ASSUMPTION': 'cat-assumption',
  'CANDIDATE EXPERIMENT': 'cat-candidate',
  'AI INTERPRETATION': 'cat-ai',
  'NOT AVAILABLE': 'cat-na',
}

const num = (v) => (v == null ? 'Not available' : v.toLocaleString('en-US', { maximumFractionDigits: 3 }))
const withUnit = (v, unit) => (v == null ? 'Not available' : unit ? `${num(v)} ${unit}` : num(v))
const signed = (v) => (v == null ? '—' : v > 0 ? `+${num(v)}` : num(v))

function Badge({ category }) {
  return <span className={`cat-badge ${CATEGORY_CLASS[category] ?? ''}`}>{category}</span>
}

function buildBody(objective, rows, maxCandidates) {
  const constraints = {}
  const errors = []
  for (const p of PARAMETERS) {
    const r = rows[p.key]
    const filled = [r.min, r.max, r.step].map((v) => v.trim() !== '')
    if (!filled.some(Boolean)) continue
    if (!filled[0] || !filled[1]) {
      errors.push(`${p.label}: enter both minimum and maximum (or leave the row empty to use the default).`)
      continue
    }
    const c = { min: Number(r.min), max: Number(r.max), changeable: r.changeable }
    if (filled[2]) c.step = Number(r.step)
    if (![c.min, c.max, c.step ?? 1].every(Number.isFinite)) errors.push(`${p.label}: enter numbers.`)
    else if (c.min > c.max) errors.push(`${p.label}: minimum must not exceed maximum.`)
    constraints[p.key] = c
  }
  return { body: { objective, constraints, max_candidates: maxCandidates }, errors }
}

function CandidateCard({ c, reference, explanation }) {
  return (
    <article className="plan-candidate" data-testid={`plan-${c.id}`}>
      <div className="card-header">
        <h4>
          {c.id} · {c.design_role}
        </h4>
        <Badge category={c.category} />
      </div>
      <p className="muted small-note">
        Changed parameters: {c.changed_parameters.length ? c.changed_parameters.map((n) => reference[n].label).join(', ') : 'none (reference conditions)'}
      </p>
      <p className="plan-legend">
        Reference <Badge category="OBSERVED DATA" /> · Candidate <Badge category="CANDIDATE EXPERIMENT" /> · Change and position{' '}
        <Badge category="DERIVED CALCULATION" />
      </p>
      <div className="table-wrap">
        <table className="plan-table">
          <thead>
            <tr>
              <th>Parameter</th>
              <th>Reference</th>
              <th>Candidate</th>
              <th>Change</th>
              <th>Position in range</th>
            </tr>
          </thead>
          <tbody>
            {c.conditions.map((x) => (
              <tr key={x.parameter} className={x.changed ? 'plan-changed' : ''}>
                <td>{x.label}</td>
                <td className="num">{withUnit(x.reference_value, x.unit)}</td>
                <td className="num">
                  {withUnit(x.value, x.unit)}
                  {x.extrapolation && <span className="plan-extrap"> extrapolation</span>}
                </td>
                <td className="num">{signed(x.change_from_reference)}</td>
                <td className="num">{x.relative_position == null ? '—' : `${Math.round(x.relative_position * 100)} %`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="plan-rationale">
        {c.rationale.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
      {c.warnings.map((w) => (
        <p key={w} className="alert alert-warning plan-warning">
          {w}
        </p>
      ))}
      {explanation && (
        <p className="plan-ai" data-testid={`plan-ai-${c.id}`}>
          <Badge category="AI INTERPRETATION" /> {explanation}
        </p>
      )}
    </article>
  )
}

export default function ExperimentPlanning({ dataVersion }) {
  const [experiment, setExperiment] = useState(null)
  const [objective, setObjective] = useState('improve_cell_density')
  const [rows, setRows] = useState(EMPTY_ROWS)
  const [maxCandidates, setMaxCandidates] = useState(5)
  const [result, setResult] = useState(null) // { body, plan }
  const [errors, setErrors] = useState([])
  const [loading, setLoading] = useState(false)
  const [ai, setAI] = useState(null)
  const [aiError, setAIError] = useState(null)
  const [aiLoading, setAILoading] = useState(false)
  const experimentId = experiment?.experiment_id

  function reset() {
    setResult(null)
    setAI(null)
    setAIError(null)
  }

  function selectExperiment(e) {
    setExperiment(e)
    setErrors([])
    reset()
  }

  const setRow = (key, field) => (e) => {
    const value = field === 'changeable' ? e.target.checked : e.target.value
    setRows((r) => ({ ...r, [key]: { ...r[key], [field]: value } }))
  }

  async function generate(e) {
    e.preventDefault()
    const { body, errors: problems } = buildBody(objective, rows, maxCandidates)
    setErrors(problems)
    if (problems.length) return
    reset()
    setLoading(true)
    try {
      setResult({ body, plan: await planExperiment(experimentId, body) })
    } catch (err) {
      setErrors([err.message])
    } finally {
      setLoading(false)
    }
  }

  async function explain() {
    setAIError(null)
    setAILoading(true)
    try {
      setAI(await interpretPlan(experimentId, result.body))
    } catch (err) {
      setAIError(err.message)
    } finally {
      setAILoading(false)
    }
  }

  const plan = result && result.plan.experiment_id === experimentId ? result.plan : null
  const reference = plan ? Object.fromEntries(plan.reference.map((r) => [r.parameter, r])) : {}
  const used = plan ? Object.fromEntries(plan.constraints.map((c) => [c.parameter, c])) : {}
  const explanations = Object.fromEntries((ai?.interpretation.candidate_explanations ?? []).map((x) => [x.candidate_id, x.explanation]))

  return (
    <section className="card planning">
      <div className="card-header">
        <h2>Experiment Planning</h2>
        <span className="cat-badge cat-candidate">CANDIDATE EXPERIMENT</span>
      </div>
      <p className="alert alert-warning plan-banner">
        Candidate conditions are suggestions from simple, deterministic design rules within the allowed ranges. They
        are not predictions of biological outcome, and no result is assured. Nothing is applied, saved or
        created.
      </p>

      <ExperimentPicker
        sources={['manual', 'csv', 'simulated']}
        value={experiment}
        onChange={selectExperiment}
        version={dataVersion}
        allowCreate={false}
        label="Reference experiment"
        noneLabel="— Select a reference experiment —"
      />
      {!experimentId && <p className="muted placeholder">Select a stored experiment as the reference.</p>}

      {experimentId && (
        <form onSubmit={generate} noValidate>
          <div className="fc-controls">
            <label>
              Objective
              <select name="plan-objective" value={objective} onChange={(e) => setObjective(e.target.value)}>
                {OBJECTIVES.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Maximum candidates
              <select name="plan-max" value={maxCandidates} onChange={(e) => setMaxCandidates(Number(e.target.value))}>
                {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <h3>Allowed ranges</h3>
          <p className="muted small-note">
            Entered values are a <Badge category="USER CONSTRAINT" />. Empty rows use the prototype default range where one
            exists (<Badge category="PLANNING ASSUMPTION" />, not a cell-line limit); aeration and feed rate have no default
            and are held at the reference. {objective === 'compare_candidates' && 'The comparison design varies only parameters with an entered range.'}
          </p>
          <div className="table-wrap">
            <table className="plan-table plan-constraints" data-testid="plan-constraints">
              <thead>
                <tr>
                  <th>Parameter</th>
                  <th>Minimum</th>
                  <th>Maximum</th>
                  <th>Step (optional)</th>
                  <th>Vary</th>
                  <th>Range used</th>
                </tr>
              </thead>
              <tbody>
                {PARAMETERS.map((p) => {
                  const u = used[p.key]
                  return (
                    <tr key={p.key}>
                      <td>
                        {p.label} {p.unit && <span className="muted">({p.unit})</span>}
                      </td>
                      {['min', 'max', 'step'].map((f) => (
                        <td key={f}>
                          <input name={`plan-${p.key}-${f}`} type="number" step="any" value={rows[p.key][f]} onChange={setRow(p.key, f)} aria-label={`${p.label} ${f}`} />
                        </td>
                      ))}
                      <td>
                        <input name={`plan-${p.key}-changeable`} type="checkbox" checked={rows[p.key].changeable} onChange={setRow(p.key, 'changeable')} aria-label={`Vary ${p.label}`} />
                      </td>
                      <td className="plan-used">
                        {u ? (
                          <>
                            {u.min == null ? 'Held at reference' : `${num(u.min)}–${num(u.max)}${u.step ? `, step ${num(u.step)}` : ''}`} <Badge category={u.category} />
                          </>
                        ) : (
                          '—'
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div className="fc-actions">
            <button type="submit" disabled={loading}>
              {loading ? 'Generating…' : 'Generate Candidates'}
            </button>
          </div>
        </form>
      )}
      {errors.map((e) => (
        <div key={e} className="alert alert-error">
          {e}
        </div>
      ))}

      {plan && (
        <div className="plan-results">
          <p className="muted small-note">{plan.disclaimer}</p>
          <h3>Reference conditions</h3>
          <div className="grid adv-cards">
            {plan.reference.map((r) => (
              <div className="metric adv-card" key={r.parameter} data-testid={`plan-ref-${r.parameter}`}>
                <div className="metric-label">{r.label}</div>
                <div className="metric-value">{withUnit(r.value, r.unit)}</div>
                <Badge category={r.category} />
              </div>
            ))}
          </div>
          {plan.warnings.map((w) => (
            <p key={w} className="alert alert-warning plan-warning">
              {w}
            </p>
          ))}
          {plan.message && <p className="alert alert-warning">{plan.message}</p>}

          {plan.candidates.length > 0 && (
            <>
              <div className="card-header">
                <h3>
                  Candidate experiments ({plan.candidates.length}
                  {plan.candidates_omitted > 0 && `; ${plan.candidates_omitted} more not shown`})
                </h3>
                <button type="button" className="secondary" onClick={explain} disabled={aiLoading}>
                  {aiLoading ? 'Asking Gemini…' : 'Explain with AI'}
                </button>
              </div>
              {aiError && <div className="alert alert-error">{aiError}</div>}
              <div className="plan-candidates">
                {plan.candidates.map((c) => (
                  <CandidateCard key={c.id} c={c} reference={reference} explanation={explanations[c.id]} />
                ))}
              </div>
            </>
          )}

          {ai && (
            <div className="plan-ai-summary" data-testid="plan-ai-summary">
              <h3>
                AI explanation <Badge category="AI INTERPRETATION" />
              </h3>
              <p className="muted small-note">{ai.notice}</p>
              {[
                ['Considerations', ai.interpretation.considerations],
                ['Uncertainties', ai.interpretation.uncertainties],
              ].map(([title, items]) =>
                items.length ? (
                  <div key={title}>
                    <div className="muted small-label">{title}</div>
                    <ul>
                      {items.map((x) => (
                        <li key={x}>{x}</li>
                      ))}
                    </ul>
                  </div>
                ) : null,
              )}
            </div>
          )}

          <details className="fc-assumptions">
            <summary>Derived calculations, assumptions and limitations</summary>
            <div className="muted small-label">
              <Badge category="DERIVED CALCULATION" />
            </div>
            <ul>
              {plan.derived_calculations.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
            <div className="muted small-label">
              <Badge category="PLANNING ASSUMPTION" />
            </div>
            <ul>
              {plan.assumptions.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
            <div className="muted small-label">Limitations</div>
            <ul>
              {plan.limitations.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
          </details>
        </div>
      )}
    </section>
  )
}
