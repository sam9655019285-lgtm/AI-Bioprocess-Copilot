import { useEffect, useState } from 'react'
import { analyzeWithAI, getAIStatus } from '../api.js'
import { buildPreservedScaleUp, SCENARIO_SCALES as SCALES } from '../scaleUpScenario.js'
import EvidenceRefs, { RejectedRefsNote } from './EvidenceRefs.jsx'
import ExperimentPicker from './ExperimentPicker.jsx'

const NOTICE =
  'AI-generated interpretation. Measurements and deterministic findings come from the application; AI interpretations should be reviewed by a scientist.'

function Section({ title, items, empty = 'None reported.', children }) {
  return (
    <section className="ai-section">
      <h3>{title}</h3>
      {items && items.length === 0 ? <p className="muted">{empty}</p> : children}
    </section>
  )
}

function Field({ label, kind, children }) {
  return (
    <div className={`ai-field${kind ? ` ai-field-${kind}` : ''}`}>
      <span className="ai-field-label">{label}</span>
      <span>{children}</span>
    </div>
  )
}

function AIResult({ result, onNavigate }) {
  const a = result.analysis
  const refs = (p) => (
    <EvidenceRefs label="Supported by" refs={p.evidence_refs} items={result.evidence_items} onNavigate={onNavigate} />
  )
  return (
    <div className="ai-result">
      <p className="ai-trust">
        <span className="cat-badge cat-ai">AI INTERPRETATION</span> Every section below is Gemini&apos;s interpretation of the
        application&apos;s deterministic results; evidence lines refer to that supplied data.
      </p>
      <p className="muted small-note">
        {result.provider} · {result.model} · {new Date(result.generated_at).toLocaleString()} · based on{' '}
        {result.observation_count} observation(s) and {result.finding_count} deterministic finding(s)
        {result.scale_up_included ? ' and a scale-up scenario' : ''}
      </p>
      <RejectedRefsNote refs={result.rejected_evidence_refs} />

      <Section title="Process Overview">
        <p className="ai-overview">{a.overview}</p>
      </Section>

      <Section title="Observed Patterns" items={a.observed_patterns}>
        <div className="ai-cards">
          {a.observed_patterns.map((p, i) => (
            <article key={i} className="ai-card ai-fact">
              <h4>{p.title}</h4>
              <Field label="Observation">{p.observation}</Field>
              <Field label="Evidence" kind="evidence">{p.evidence}</Field>
              {refs(p)}
            </article>
          ))}
        </div>
      </Section>

      <Section title="Possible Interpretations" items={a.possible_interpretations}>
        <div className="ai-cards">
          {a.possible_interpretations.map((p, i) => (
            <article key={i} className="ai-card ai-interpretation">
              <h4>{p.title}</h4>
              <Field label="Interpretation">{p.interpretation}</Field>
              <Field label="Supporting evidence" kind="evidence">{p.supporting_evidence}</Field>
              <Field label="Uncertainty" kind="uncertainty">{p.uncertainty}</Field>
              {refs(p)}
            </article>
          ))}
        </div>
      </Section>

      <Section title="Attention Points" items={a.attention_points}>
        <div className="ai-cards">
          {a.attention_points.map((p, i) => (
            <article key={i} className="ai-card ai-attention">
              <h4>
                {p.title} <span className="treat-badge treat-baseline">{p.finding_type}</span>
              </h4>
              <p>{p.explanation}</p>
              {refs(p)}
            </article>
          ))}
        </div>
      </Section>

      {result.scale_up_included && (
        <Section title="Scale-Up Considerations" items={a.scale_up_considerations}>
          <p className="muted small-note">Based on an illustrative scale-up scenario, not a validated prediction.</p>
          <div className="ai-cards">
            {a.scale_up_considerations.map((p, i) => (
              <article key={i} className="ai-card">
                <h4>{p.title}</h4>
                <Field label="Consideration">{p.consideration}</Field>
                <Field label="Basis" kind="evidence">{p.basis}</Field>
              </article>
            ))}
          </div>
        </Section>
      )}

      <Section title="Questions for Further Investigation" items={a.questions_for_investigation}>
        <ul className="summary-list">
          {a.questions_for_investigation.map((q, i) => (
            <li key={i}>{q}</li>
          ))}
        </ul>
      </Section>
    </div>
  )
}

/** Gemini interpretation of the deterministic analysis (Phase 5), findings (Phase 7) and optional scale-up (Phase 6). */
export default function AIProcessAnalysis({ active, dataVersion, onAIAnalysis, onNavigate }) {
  const [configured, setConfigured] = useState(null) // null = unknown
  const [statusError, setStatusError] = useState(null)
  const [experiment, setExperiment] = useState(null)
  const [includeScaleUp, setIncludeScaleUp] = useState(false)
  const [targetScale, setTargetScale] = useState(100)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const experimentId = experiment?.experiment_id

  useEffect(() => {
    if (!active) return
    getAIStatus()
      .then((s) => {
        setConfigured(s.configured)
        setStatusError(null)
      })
      .catch((err) => setStatusError(err.message))
  }, [active])

  useEffect(() => {
    setResult(null)
    setError(null)
  }, [experimentId])

  async function handleAnalyze() {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const body = includeScaleUp ? { scale_up: await buildPreservedScaleUp(experimentId, targetScale) } : {}
      const analysis = await analyzeWithAI(experimentId, body)
      setResult(analysis)
      onAIAnalysis?.(experimentId, analysis)
    } catch (err) {
      if (err.status === 503) setConfigured(false)
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="card ai-analysis">
      <div className="card-header">
        <h2>AI Process Analysis</h2>
        <span
          className={`treat-badge ${configured ? 'treat-preserved' : 'treat-na'}`}
          role="status"
          data-testid="ai-status"
        >
          {configured == null ? 'Checking Gemini…' : configured ? 'Gemini configured' : 'Gemini not configured'}
        </span>
      </div>
      <p className="alert alert-warning ai-notice">{NOTICE}</p>
      {statusError && <div className="alert alert-error">Could not check the AI status: {statusError}</div>}
      {configured === false && (
        <div className="alert alert-error ai-not-configured">
          Gemini is not configured on the server. Set <code>GEMINI_API_KEY</code> for the backend (for example in{' '}
          <code>backend/.env</code>, see README) and restart it. Process Monitoring, Anomalies and Scale-Up keep working
          without it.
        </div>
      )}

      <ExperimentPicker
        sources={['manual', 'csv', 'simulated']}
        value={experiment}
        onChange={setExperiment}
        version={dataVersion}
        allowCreate={false}
      />

      {experimentId && (
        <div className="ai-controls">
          <label className="ai-checkbox">
            <input type="checkbox" checked={includeScaleUp} onChange={(e) => setIncludeScaleUp(e.target.checked)} />
            Include an illustrative scale-up scenario
          </label>
          {includeScaleUp && (
            <div className="chip-group" aria-label="Target scale">
              {SCALES.map((s) => (
                <button
                  type="button"
                  key={s}
                  className={`chip ${targetScale === s ? 'chip-active' : ''}`}
                  onClick={() => setTargetScale(s)}
                >
                  {s} L
                </button>
              ))}
            </div>
          )}
          <button onClick={handleAnalyze} disabled={loading || !configured}>
            {loading ? 'Analyzing…' : 'Analyze with Gemini'}
          </button>
        </div>
      )}
      {includeScaleUp && experimentId && (
        <p className="muted small-note">
          The scenario keeps the source's latest values at the chosen target scale (see the Scale-Up tab for the
          calculations). It is illustrative, not a validated prediction.
        </p>
      )}
      {!experimentId && <p className="muted placeholder">Select an experiment to analyse.</p>}

      {loading && (
        <div className="ai-loading" role="status">
          <span className="spinner" aria-hidden="true" /> Gemini is analysing the deterministic results for{' '}
          {experimentId}… this can take up to a minute.
        </div>
      )}
      {error && <div className="alert alert-error">{error}</div>}
      {result && result.experiment_id === experimentId && <AIResult result={result} onNavigate={onNavigate} />}
    </section>
  )
}
