import { useEffect, useState } from 'react'
import { getExperimentAnalysis, getExperimentAnomalies, simulateScaleUp } from '../api.js'
import { alertedParameters } from '../useSimulator.js'
import BioreactorVessel from './BioreactorVessel.jsx'
import ExperimentPicker from './ExperimentPicker.jsx'
import LiveAlerts from './LiveAlerts.jsx'
import MetricCard from './MetricCard.jsx'
import ProcessTrendCharts from './ProcessTrendCharts.jsx'
import SourceBadge from './SourceBadge.jsx'

/*
 * Bioprocess Command Center: an aggregation/presentation layer only. Every value comes from
 * an existing source — Phase 5 analysis, Phase 7 anomalies, the Phase 6 scale-up endpoint,
 * the shared simulator state, and AI/Copilot results already generated in this session.
 * It computes nothing new and never calls Gemini.
 */

const KEY_METRICS = [
  { key: 'cell_density', label: 'Cell density', unit: '×10⁶ cells/mL', digits: 2 },
  { key: 'dissolved_oxygen_percent', label: 'Dissolved O₂', unit: '% air sat.', digits: 1 },
  { key: 'ph', label: 'pH', unit: '', digits: 2 },
  { key: 'temperature_c', label: 'Temperature', unit: '°C', digits: 1 },
  { key: 'agitation_rpm', label: 'Agitation', unit: 'rpm', digits: 0 },
  { key: 'culture_time_hours', label: 'Culture time', unit: 'h', digits: 1 },
  { key: 'feed_rate', label: 'Feed', unit: 'mL/h', digits: 2 },
  { key: 'aeration_rate', label: 'Aeration', unit: 'vvm', digits: 3 },
]
const TREND_PARAMETERS = new Set(['cell_density', 'dissolved_oxygen_percent', 'ph', 'temperature_c', 'agitation_rpm'])
const MAX_FINDINGS = 5
const hours = (h) => (h == null ? 'Not available' : `${Number(h.toFixed(2))} h`)
const num = (v, d = 3) => (v == null ? 'Not available' : v.toLocaleString('en-US', { maximumFractionDigits: d }))

function Panel({ title, action, children, className = '' }) {
  return (
    <section className={`cc-panel ${className}`} aria-label={title}>
      <div className="cc-panel-head">
        <h3>{title}</h3>
        {action}
      </div>
      {children}
    </section>
  )
}

// SIMULATED DEMO WORKFLOW (Phase 19A): navigation only; every action stays on its own page.
const DEMO_STEPS = [
  { page: 'simulator', label: 'Simulated Bioreactor', hint: 'Save to DEMO-LIVE and press START.' },
  { page: 'simulator', label: 'Inject simulated disturbance', hint: 'Choose DO −35 % air sat. and press Inject disturbance.' },
  { page: 'simulator', label: 'Inspect alert', hint: 'Open the alert and its evidence in Live alerts.' },
  { page: 'simulator', label: 'Find precedents', hint: 'In the alert detail: the same rule in stored runs.' },
  { page: 'comparison', label: 'Compare runs', hint: 'Or use "Compare with this run" from a precedent.' },
  { page: 'scaleup', label: 'Scale-Up', hint: 'Engineering estimates with labelled assumptions.' },
  { page: 'forecasting', label: 'Forecasting', hint: 'Illustrative model forecast.' },
  { page: 'planning', label: 'Experiment Planning', hint: 'Candidate conditions within allowed ranges.' },
  { page: 'copilot', label: 'AI Copilot', hint: 'Gemini runs only when you ask.' },
  { page: 'report', label: 'Report', hint: 'Download the PDF.' },
]

function DemoWorkflow({ sim, onNavigate }) {
  const simState = sim.status === 'simulating' ? 'running' : sim.run ? 'paused' : 'no run'
  return (
    <details className="cc-demo" data-testid="demo-workflow">
      <summary>
        <span className="cat-badge cat-assumption">SIMULATED DEMO WORKFLOW</span> Suggested demonstration path
        <span className="muted small-note"> · simulator: {simState} · {sim.unacknowledged} unacknowledged live alert(s)</span>
      </summary>
      <p className="muted small-note">
        Buttons only open the relevant page; starting the simulator, injecting a disturbance and asking Gemini stay explicit
        actions on those pages. Demo data is simulated (seed it with <code>python -m app.demo_seed</code>), not laboratory data.
      </p>
      <ol className="cc-demo-steps">
        {DEMO_STEPS.map((s) => (
          <li key={s.label}>
            <button type="button" className="link-button" onClick={() => onNavigate?.(s.page)}>
              {s.label}
            </button>
            <span className="muted small-note"> — {s.hint}</span>
          </li>
        ))}
      </ol>
    </details>
  )
}

function LinkButton({ onClick, children }) {
  return (
    <button type="button" className="secondary small" onClick={onClick}>
      {children}
    </button>
  )
}

export default function CommandCenter({
  sim, active, dataVersion, onNavigate, aiAnalyses = {}, copilotReplies = {}, scaleUpScenarios = {},
}) {
  const [experiment, setExperiment] = useState(null)
  const [data, setData] = useState(null) // { id, analysis, anomalies }
  const [error, setError] = useState(null)
  const [scaleUp, setScaleUp] = useState(null) // { key, result } | { key, error }
  const experimentId = experiment?.experiment_id
  const scenario = experimentId ? scaleUpScenarios[experimentId] : null
  const scenarioKey = scenario ? JSON.stringify(scenario) : null

  // Stored data: one fetch per experiment / data change, only while the page is shown.
  useEffect(() => {
    if (!experimentId || !active) return
    let cancelled = false
    setError(null)
    Promise.all([getExperimentAnalysis(experimentId), getExperimentAnomalies(experimentId)])
      .then(([analysis, anomalies]) => !cancelled && setData({ id: experimentId, analysis, anomalies }))
      .catch((err) => !cancelled && setError(`Could not load experiment data: ${err.message}`))
    return () => {
      cancelled = true
    }
  }, [experimentId, active, dataVersion])

  // Scale-up snapshot: the existing (read-only) scale-up endpoint for the Scale-Up page's scenario.
  useEffect(() => {
    if (!scenarioKey || !active) return
    let cancelled = false
    simulateScaleUp(JSON.parse(scenarioKey))
      .then((result) => !cancelled && setScaleUp({ key: scenarioKey, result }))
      .catch((err) => !cancelled && setScaleUp({ key: scenarioKey, error: err.message }))
    return () => {
      cancelled = true
    }
  }, [scenarioKey, active, dataVersion])

  const shown = data?.id === experimentId ? data : null
  const a = shown?.analysis
  const an = shown?.anomalies
  // Live values only when the shared simulator run is saving into this experiment.
  const liveRun = sim.run && sim.run.saving_to === experimentId
  const liveLatest = liveRun ? sim.history.at(-1) : null
  const latest = liveLatest ?? a?.latest_observation ?? null
  const simState = !liveRun
    ? { id: 'none', label: 'No live simulation' }
    : sim.connection === 'closed'
      ? { id: 'error', label: 'Simulator disconnected' }
      : sim.status === 'simulating'
        ? { id: 'running', label: 'Running' }
        : { id: 'paused', label: 'Paused' }
  const snapshot = scaleUp?.key === scenarioKey ? scaleUp : null
  const ai = experimentId ? aiAnalyses[experimentId] : null
  const copilot = experimentId ? copilotReplies[experimentId] : null
  const go = (page) => onNavigate?.(page)

  return (
    <section className="card command-center">
      <div className="card-header">
        <h2>Bioprocess Command Center</h2>
      </div>
      <p className="muted disclaimer">
        One view of an experiment, assembled from the application's existing analysis, anomaly checks, scale-up
        scenario, simulator and AI results. It adds no new calculations or scores.
      </p>
      <DemoWorkflow sim={sim} onNavigate={onNavigate} />
      <ExperimentPicker
        sources={['manual', 'csv', 'simulated']}
        value={experiment}
        onChange={setExperiment}
        version={dataVersion}
        allowCreate={false}
      />
      {!experimentId && <p className="muted placeholder">Select an experiment to open the Bioprocess Command Center.</p>}
      {error && <div className="alert alert-error">{error}</div>}
      {experimentId && !shown && !error && <p className="muted">Loading experiment…</p>}

      {shown && (
        <>
          <div className="cc-status" aria-label="Experiment status">
            <div>
              <div className="muted small-label">Experiment</div>
              <strong>{a.experiment.experiment_id}</strong> <span className="muted">{a.experiment.name}</span>
            </div>
            <div>
              <div className="muted small-label">Scale</div>
              <strong>{a.experiment.scale_liters} L</strong>
            </div>
            <div>
              <div className="muted small-label">Source</div>
              <SourceBadge source={a.experiment.data_source} />
            </div>
            <div>
              <div className="muted small-label">Created</div>
              <span>{new Date(a.experiment.created_at).toLocaleString()}</span>
            </div>
            <div>
              <div className="muted small-label">Culture time</div>
              <strong>{hours(latest?.culture_time_hours ?? null)}</strong>
            </div>
            <div>
              <div className="muted small-label">Simulation</div>
              <span className={`bx-status bx-status-${simState.id === 'none' ? 'stopped' : simState.id}`} data-testid="cc-sim-status">
                <span className="dot" aria-hidden="true" />
                {simState.label}
              </span>
            </div>
          </div>
          {a.experiment.data_source === 'simulated' && (
            <div className="alert alert-warning cc-notice">
              Simulated experiment — values are illustrative and not calibrated to a specific physical bioreactor.
            </div>
          )}

          <p className="muted small-note" data-testid="cc-value-source">
            {liveLatest
              ? `Latest values: live simulator run (${sim.status === 'simulating' ? 'running' : 'paused'}).`
              : a.observation_count
                ? `Latest values: last stored observation at ${hours(a.culture_end_hours)}.`
                : 'No observations recorded yet.'}
          </p>
          <div className="metrics cc-metrics">
            {KEY_METRICS.map((m) => (
              <MetricCard key={m.key} label={m.label} value={latest?.[m.key] ?? null} unit={m.unit} digits={m.digits} missing="Not available" />
            ))}
          </div>

          <div className="cc-grid">
            <Panel title="Live bioreactor" action={<LinkButton onClick={() => go('bioreactor')}>Open Full Bioreactor View</LinkButton>}>
              {active && (
                <div className="cc-vessel">
                  <BioreactorVessel
                    values={latest}
                    running={liveRun && sim.status === 'simulating'}
                    volumeLiters={a.experiment.scale_liters}
                    highlight={liveRun ? alertedParameters(sim.alerts, experimentId) : undefined}
                  />
                </div>
              )}
              <p className="muted small-note">
                Illustrative visualization of the {liveLatest ? 'live simulator values' : 'latest stored values'}; animated only
                while a simulator run for this experiment is running.
              </p>
            </Panel>

            <Panel title="Live alerts" action={<LinkButton onClick={() => go('simulator')}>Open Simulated Bioreactor</LinkButton>}>
              {sim.run && !liveRun && (
                <p className="muted small-note">The active simulator run ({sim.run.experiment_id}) is not saving to this experiment.</p>
              )}
              <LiveAlerts sim={sim} compact onNavigate={onNavigate} />
            </Panel>

            <Panel title="Process status" action={<LinkButton onClick={() => go('monitoring')}>Analyze Process</LinkButton>}>
              <dl className="details cc-details">
                <dt>Observations</dt>
                <dd>{a.observation_count}</dd>
                <dt>Culture duration</dt>
                <dd>{hours(a.culture_duration_hours)}</dd>
                <dt>Time points</dt>
                <dd>
                  {a.data_quality.distinct_time_points} distinct, {a.data_quality.duplicate_time_points} repeated
                </dd>
                <dt>Trend charts</dt>
                <dd>{a.data_quality.enough_for_trends ? 'Available' : 'Not available (fewer than 2 time points)'}</dd>
              </dl>
              <ul className="summary-list cc-summary">
                {a.summary.slice(0, 4).map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </Panel>

            <Panel title="Process trends" className="cc-wide">
              {a.data_quality.enough_for_trends ? (
                active && (
                  <ProcessTrendCharts observations={a.observations} parameters={a.parameters.filter((p) => TREND_PARAMETERS.has(p.parameter))} />
                )
              ) : (
                <p className="muted placeholder">Insufficient data for trend.</p>
              )}
              <p className="muted small-note">Stored observations for this experiment.</p>
            </Panel>

            <Panel title="Findings" action={<LinkButton onClick={() => go('anomalies')}>View Anomalies</LinkButton>}>
              <p data-testid="cc-findings-counts">
                <strong>{an.finding_count}</strong> finding(s): <span className="sev-badge sev-significant">SIGNIFICANT</span>{' '}
                {an.counts.significant} · <span className="sev-badge sev-attention">ATTENTION</span> {an.counts.attention} ·{' '}
                <span className="sev-badge sev-info">INFO</span> {an.counts.info}
              </p>
              {a.observation_count === 0 ? (
                <p className="muted">No observations, so no checks were run.</p>
              ) : an.finding_count === 0 ? (
                <p className="muted">No anomaly findings detected by the current rule set.</p>
              ) : (
                <ul className="compare-findings" data-testid="cc-findings">
                  {an.findings.slice(0, MAX_FINDINGS).map((f) => (
                    <li key={f.finding_id}>
                      <span className={`sev-badge sev-${f.severity}`}>{f.severity.toUpperCase()}</span> {f.message}
                    </li>
                  ))}
                </ul>
              )}
              {an.finding_count > MAX_FINDINGS && (
                <p className="muted small-note">Showing the {MAX_FINDINGS} most severe of {an.finding_count} (existing severity order).</p>
              )}
            </Panel>

            <Panel title="Scale-up scenario" action={<LinkButton onClick={() => go('scaleup')}>Open Scale-Up Simulator</LinkButton>}>
              {!scenario ? (
                <p className="muted" data-testid="cc-scaleup-empty">No scale-up scenario selected.</p>
              ) : !snapshot ? (
                <p className="muted">Loading scenario…</p>
              ) : snapshot.error ? (
                <div className="alert alert-error">Could not load the scenario: {snapshot.error}</div>
              ) : (
                <>
                  <span className="treat-badge treat-scenario">Scenario calculation</span>
                  <dl className="details cc-details" data-testid="cc-scaleup">
                    <dt>Source</dt>
                    <dd>{num(snapshot.result.source.scale_liters)} L</dd>
                    <dt>Target</dt>
                    <dd>{num(snapshot.result.target_scale_liters)} L</dd>
                    <dt>Scale factor</dt>
                    <dd>{num(snapshot.result.scale_factor)}×</dd>
                    <dt>Volume increase</dt>
                    <dd>{num(snapshot.result.volume_increase_liters)} L</dd>
                    <dt>Target gas flow</dt>
                    <dd>{snapshot.result.gas_flow.target_l_per_min == null ? 'Not available' : `${num(snapshot.result.gas_flow.target_l_per_min)} L/min`}</dd>
                    <dt>Target feed per L</dt>
                    <dd>{snapshot.result.feed.target_ml_per_h_per_l == null ? 'Not available' : `${num(snapshot.result.feed.target_ml_per_h_per_l)} mL/h per L`}</dd>
                  </dl>
                  <p className="muted small-note">
                    Baseline assumptions: cell density and culture duration are carried over from the source. {snapshot.result.disclaimer}
                  </p>
                </>
              )}
            </Panel>

            <Panel title="AI process analysis" action={<LinkButton onClick={() => go('ai')}>View full AI Analysis</LinkButton>}>
              {ai ? (
                <>
                  <span className="treat-badge treat-baseline">AI-generated interpretation</span>
                  <p className="cc-ai" data-testid="cc-ai">{ai.analysis.overview}</p>
                  <p className="muted small-note">
                    {ai.model} · {new Date(ai.generated_at).toLocaleTimeString()} · not observed experimental data.
                  </p>
                </>
              ) : (
                <p className="muted" data-testid="cc-ai-empty">AI analysis has not been generated for this experiment.</p>
              )}
            </Panel>

            <Panel title="AI Copilot" action={<LinkButton onClick={() => go('copilot')}>Open AI Copilot</LinkButton>}>
              {copilot ? (
                <>
                  <span className="treat-badge treat-baseline">AI-generated</span>
                  <p className="cc-ai">
                    <strong>{copilot.question}</strong> {copilot.answer}
                  </p>
                </>
              ) : (
                <p className="muted">Ask about this experiment in the AI Copilot. No answer in this session yet.</p>
              )}
            </Panel>

            <Panel title="Quick actions">
              <div className="cc-actions">
                {[
                  ['+ New Experiment', 'experiment-data'],
                  ['Open Bioreactor', 'bioreactor'],
                  ['Analyze Process', 'monitoring'],
                  ['Run Scale-Up', 'scaleup'],
                  ['View Anomalies', 'anomalies'],
                  ['Ask AI Copilot', 'copilot'],
                  ['Compare Experiments', 'comparison'],
                  ['Generate Report', 'report'],
                ].map(([label, page]) => (
                  <button type="button" key={label} className="secondary" onClick={() => go(page)}>
                    {label}
                  </button>
                ))}
              </div>
            </Panel>
          </div>
          <p className="muted small-note cc-disclaimer">
            Decision-support prototype. Findings use prototype monitoring rules; scale-up values are scenario calculations;
            AI content is interpretation. It does not control a physical bioreactor.
          </p>
        </>
      )}
    </section>
  )
}
