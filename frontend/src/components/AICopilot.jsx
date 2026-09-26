import { useEffect, useState } from 'react'
import { askCopilot, getAIStatus, getExperimentAnalysis, getExperimentAnomalies } from '../api.js'
import { buildPreservedScaleUp, SCENARIO_SCALES } from '../scaleUpScenario.js'
import ExperimentPicker from './ExperimentPicker.jsx'
import SourceBadge from './SourceBadge.jsx'

const NOTICE =
  'This Copilot is a decision-support prototype. It does not control a physical bioreactor and does not replace scientist or process-engineering judgment.'

const QUICK_QUESTIONS = [
  'Summarize this experiment.',
  'What changed most?',
  'Why did DO decrease?',
  'What anomalies were detected?',
  'What should I investigate first?',
  'What should I check before scale-up?',
  'What information is missing?',
]

const hours = (h) => `${Number(h.toFixed(2))} h`

function ContextSummary({ analysis, anomalies }) {
  const exp = analysis.experiment
  const c = anomalies.counts
  return (
    <dl className="exp-facts copilot-context" aria-label="Experiment context">
      <div>
        <dt>Experiment</dt>
        <dd>{exp.experiment_id}</dd>
      </div>
      <div>
        <dt>Scale</dt>
        <dd>{exp.scale_liters} L</dd>
      </div>
      <div>
        <dt>Observations</dt>
        <dd>{analysis.observation_count}</dd>
      </div>
      <div>
        <dt>Culture duration</dt>
        <dd>{analysis.culture_duration_hours == null ? '—' : hours(analysis.culture_duration_hours)}</dd>
      </div>
      <div>
        <dt>Source</dt>
        <dd>
          <SourceBadge source={exp.data_source} />
        </dd>
      </div>
      <div>
        <dt>Findings</dt>
        <dd>
          {anomalies.finding_count} ({c.significant} significant · {c.attention} attention · {c.info} info)
        </dd>
      </div>
    </dl>
  )
}

function ListSection({ title, items, empty }) {
  return (
    <section className="copilot-section">
      <h4>{title}</h4>
      {items.length === 0 ? (
        <p className="muted">{empty}</p>
      ) : (
        <ul className="evidence-list">
          {items.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** Contextual decision-support assistant for one stored experiment (deterministic context, Gemini interpretation). */
export default function AICopilot({ active, dataVersion, aiAnalyses = {}, forecastSettings = {}, onCopilotReply }) {
  const [configured, setConfigured] = useState(null)
  const [experiment, setExperiment] = useState(null)
  const [context, setContext] = useState(null) // { analysis, anomalies } for the summary
  const [contextError, setContextError] = useState(null)
  const [message, setMessage] = useState('')
  const [includeScaleUp, setIncludeScaleUp] = useState(false)
  const [targetScale, setTargetScale] = useState(100)
  const [includeAI, setIncludeAI] = useState(true)
  const [includeForecast, setIncludeForecast] = useState(false)
  const [reply, setReply] = useState(null)
  const [pending, setPending] = useState(null) // question being answered
  const [error, setError] = useState(null)
  const experimentId = experiment?.experiment_id
  const previousAI = experimentId ? aiAnalyses[experimentId] : null
  // Forecast settings last used on the Forecasting page; the backend recomputes the forecast from them.
  const forecast = experimentId ? forecastSettings[experimentId] : null

  useEffect(() => {
    if (!active) return
    getAIStatus()
      .then((s) => setConfigured(s.configured))
      .catch(() => setConfigured(null))
  }, [active])

  useEffect(() => {
    setReply(null)
    setError(null)
    if (!experimentId) {
      setContext(null)
      return
    }
    if (!active) return
    let cancelled = false
    Promise.all([getExperimentAnalysis(experimentId), getExperimentAnomalies(experimentId)])
      .then(([analysis, anomalies]) => {
        if (cancelled) return
        setContext({ analysis, anomalies })
        setContextError(null)
      })
      .catch((err) => !cancelled && setContextError(`Could not load the experiment context: ${err.message}`))
    return () => {
      cancelled = true
    }
  }, [experimentId, active, dataVersion])

  const loading = pending !== null
  const canAsk = Boolean(experimentId) && configured === true && !loading

  async function ask(question) {
    const text = question.trim()
    if (!text || !canAsk) return
    setMessage(text)
    setPending(text)
    setError(null)
    setReply(null) // never show an earlier answer next to a new question's result or error
    try {
      const body = { message: text }
      if (includeScaleUp) body.scale_up = await buildPreservedScaleUp(experimentId, targetScale)
      if (includeAI && previousAI) body.ai_analysis = previousAI.analysis
      if (includeForecast && forecast) body.forecast = forecast
      const answer = await askCopilot(experimentId, body)
      setReply(answer)
      onCopilotReply?.(experimentId, answer)
    } catch (err) {
      if (err.status === 503 && /not configured/i.test(err.message)) setConfigured(false)
      setError(err.message)
    } finally {
      setPending(null)
    }
  }

  const shownContext = context?.analysis.experiment.experiment_id === experimentId ? context : null

  return (
    <section className="card copilot">
      <div className="card-header">
        <h2>AI Copilot</h2>
        <span className={`treat-badge ${configured ? 'treat-preserved' : 'treat-na'}`} data-testid="ai-status" role="status">
          {configured == null ? 'Checking Gemini…' : configured ? 'Gemini configured' : 'Gemini not configured'}
        </span>
      </div>
      <p className="alert alert-warning copilot-notice">{NOTICE}</p>
      {configured === false && (
        <div className="alert alert-error ai-not-configured">
          Gemini is not configured on the server. Set <code>GEMINI_API_KEY</code> for the backend (see README) and
          restart it. The deterministic pages keep working without it.
        </div>
      )}

      <ExperimentPicker
        sources={['manual', 'csv', 'simulated']}
        value={experiment}
        onChange={setExperiment}
        version={dataVersion}
        allowCreate={false}
      />
      {!experimentId && <p className="muted placeholder">Select an experiment. The Copilot answers about one experiment at a time.</p>}
      {contextError && <div className="alert alert-error">{contextError}</div>}

      {experimentId && shownContext && (
        <>
          <ContextSummary analysis={shownContext.analysis} anomalies={shownContext.anomalies} />
          {shownContext.analysis.experiment.data_source === 'simulated' && (
            <p className="muted small-note">Simulated data: answers describe software-generated values, not laboratory measurements.</p>
          )}

          <div className="copilot-options">
            <label className="ai-checkbox">
              <input type="checkbox" checked={includeScaleUp} onChange={(e) => setIncludeScaleUp(e.target.checked)} />
              Include an illustrative scale-up scenario
            </label>
            {includeScaleUp && (
              <div className="chip-group" aria-label="Target scale">
                {SCENARIO_SCALES.map((s) => (
                  <button type="button" key={s} className={`chip ${targetScale === s ? 'chip-active' : ''}`} onClick={() => setTargetScale(s)}>
                    {s} L
                  </button>
                ))}
              </div>
            )}
            {previousAI && (
              <label className="ai-checkbox">
                <input type="checkbox" checked={includeAI} onChange={(e) => setIncludeAI(e.target.checked)} />
                Include the AI Process Analysis from {new Date(previousAI.generated_at).toLocaleTimeString()}
              </label>
            )}
            {forecast && (
              <label className="ai-checkbox">
                <input type="checkbox" name="include-forecast" checked={includeForecast} onChange={(e) => setIncludeForecast(e.target.checked)} />
                Include the illustrative process forecast (settings from the Forecasting page)
              </label>
            )}
          </div>

          <div className="quick-questions" aria-label="Example questions">
            {QUICK_QUESTIONS.map((q) => (
              <button type="button" key={q} className="chip-question" disabled={!canAsk} onClick={() => ask(q)}>
                {q}
              </button>
            ))}
          </div>

          <form
            className="copilot-input"
            onSubmit={(e) => {
              e.preventDefault()
              ask(message)
            }}
          >
            <textarea
              aria-label="Question for the Copilot"
              rows={2}
              maxLength={2000}
              placeholder={`Ask about ${experimentId}, e.g. "Why did DO decrease?"`}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  ask(message)
                }
              }}
            />
            <button type="submit" disabled={!canAsk || !message.trim()}>
              {loading ? 'Asking…' : 'Send'}
            </button>
          </form>
        </>
      )}

      {loading && (
        <div className="ai-loading" role="status">
          <span className="spinner" aria-hidden="true" /> The Copilot is answering “{pending}” for {experimentId}…
        </div>
      )}
      {error && <div className="alert alert-error">{error}</div>}

      {reply && reply.experiment_id === experimentId && !loading && (
        <article className="copilot-reply">
          <p className="copilot-question">
            <span className="muted">Question about {reply.experiment_id}:</span> {reply.question}
          </p>
          <section className="copilot-section">
            <h4>Answer</h4>
            <p className="copilot-answer">{reply.answer}</p>
          </section>
          <ListSection title="Evidence from the experiment data" items={reply.evidence} empty="No specific evidence cited." />
          <ListSection title="Uncertainties" items={reply.uncertainties} empty="None stated." />
          <section className="copilot-section">
            <h4>Suggested follow-up questions</h4>
            {reply.suggested_questions.length === 0 ? (
              <p className="muted">None suggested.</p>
            ) : (
              <div className="quick-questions">
                {reply.suggested_questions.map((q) => (
                  <button type="button" key={q} className="chip-question" disabled={!canAsk} onClick={() => ask(q)}>
                    {q}
                  </button>
                ))}
              </div>
            )}
          </section>
          <p className="muted small-note">
            {reply.provider} · {reply.model} · {new Date(reply.generated_at).toLocaleTimeString()} · context:{' '}
            {reply.context.observation_count} observation(s), {reply.context.findings_in_context} of{' '}
            {reply.context.finding_count} finding(s)
            {reply.context.scale_up_included ? ', scale-up scenario' : ''}
            {reply.context.ai_analysis_included ? ', earlier AI analysis' : ''}. AI-generated; review before relying on it.
          </p>
        </article>
      )}
    </section>
  )
}
