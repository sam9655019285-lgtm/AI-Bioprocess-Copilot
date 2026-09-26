import { useState } from 'react'
import { askCopilot } from '../api.js'

/*
 * Live Alerts (Phase 17): alerts streamed by the simulator WebSocket. Detection is done by the
 * backend's existing anomaly rules (monitoring.py re-runs anomaly.detect); this component only
 * displays alerts from the shared `sim` state. Gemini is called only when the user clicks
 * "Explain with AI", and only for saved runs (the Copilot re-detects from stored data).
 */

const EXPLAIN_QUESTION =
  'Explain this alert: what changed, what data supports it, what might be worth inspecting, and what remains uncertain. ' +
  'Do not give bioreactor control instructions.'
const MAX_POINTS = 12

const hours = (t) => (t == null ? '—' : `${Number(t.toFixed(2))} h`)
const newestFirst = (alerts) => [...alerts].sort((a, b) => b.received_at - a.received_at)
// Alert keys are unique within a run; a new run can reuse one, so UI state is scoped to run + alert.
const uid = (a) => `${a.experiment_id}|${a.alert_id}`

function SeverityBadge({ severity }) {
  return <span className={`sev-badge sev-${severity}`}>{severity.toUpperCase()}</span>
}

function AlertDetail({ alert, explanation, onExplain }) {
  const f = alert.finding
  const points = f.points.slice(-MAX_POINTS)
  return (
    <div className="alert-detail" data-testid="alert-detail">
      <p className="muted small-note">
        {f.type_label} · first detected at culture time {hours(alert.detected_at_hours)} · run <strong>{alert.experiment_id}</strong>
        {alert.saved ? ' (saved)' : ' (preview only, not saved)'}
      </p>
      <div className="muted small-label">Evidence (deterministic rule)</div>
      <ul className="alert-evidence">
        {f.evidence.map((e) => (
          <li key={e}>{e}</li>
        ))}
      </ul>
      {points.length > 0 && (
        <div className="table-wrap">
          <table className="alert-points">
            <thead>
              <tr>
                <th>Culture time</th>
                <th>{f.parameter_label ?? 'Value'}</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.culture_time_hours}>
                  <td className="num">{hours(p.culture_time_hours)}</td>
                  <td className="num">
                    {p.value}
                    {f.unit ? ` ${f.unit}` : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {f.points.length > MAX_POINTS && <p className="muted small-note">Latest {MAX_POINTS} of {f.points.length} evidence points.</p>}
        </div>
      )}
      <p className="muted small-note">
        An alert reports that a prototype monitoring rule was met. It does not prove a biological problem; the scientist
        decides what to investigate.
      </p>
      <div className="alert-ai">
        <button type="button" className="secondary small" onClick={onExplain} disabled={!alert.saved || alert.stale || explanation?.loading}>
          {explanation?.loading ? 'Asking Gemini…' : 'Explain with AI'}
        </button>{' '}
        {!alert.saved && <span className="muted small-note">AI explanation is available only for runs saved to an experiment.</span>}
        {alert.saved && alert.stale && <span className="muted small-note">This run has ended; open the AI Copilot for stored data.</span>}
        {explanation?.error && <div className="alert alert-error">{explanation.error}</div>}
        {explanation?.reply && (
          <div className="alert-ai-reply" data-testid="alert-ai-reply">
            <span className="cat-badge cat-ai">AI INTERPRETATION</span>
            <p>{explanation.reply.answer}</p>
            {[
              ['Supporting data', explanation.reply.evidence],
              ['Uncertainties', explanation.reply.uncertainties],
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
            <p className="muted small-note">{explanation.reply.notice}</p>
          </div>
        )}
      </div>
    </div>
  )
}

/** `sim` is the shared simulator connection. `compact` renders the Command Center summary. */
export default function LiveAlerts({ sim, compact = false, onNavigate }) {
  const [openId, setOpenId] = useState(null)
  const [explanations, setExplanations] = useState({})
  const alerts = newestFirst(sim.alerts)

  if (compact) {
    return (
      <div className="live-alerts-compact" data-testid="live-alerts-compact">
        <p>
          <strong>{sim.unacknowledged}</strong> unacknowledged live alert(s){sim.run ? ` · run ${sim.run.experiment_id}` : ''}
        </p>
        {alerts.length === 0 ? (
          <p className="muted small-note">No live alerts{sim.run ? ' so far in this run' : ' — no simulator run active'}.</p>
        ) : (
          <ul className="live-alert-list">
            {alerts.slice(0, 3).map((a) => (
              <li key={uid(a)} className={a.acknowledged ? 'acknowledged' : ''}>
                <SeverityBadge severity={a.finding.severity} /> {a.finding.message}
              </li>
            ))}
          </ul>
        )}
        <button type="button" className="secondary small" onClick={() => onNavigate?.('simulator')}>
          View live alerts
        </button>
      </div>
    )
  }

  async function explain(alert) {
    const key = uid(alert)
    setExplanations((m) => ({ ...m, [key]: { loading: true } }))
    try {
      const reply = await askCopilot(alert.experiment_id, { message: EXPLAIN_QUESTION, alert: { alert_id: alert.alert_id } })
      setExplanations((m) => ({ ...m, [key]: { reply } }))
    } catch (err) {
      setExplanations((m) => ({ ...m, [key]: { error: err.message } }))
    }
  }

  return (
    <section className="live-alerts" data-testid="live-alerts">
      <div className="card-header">
        <h3>
          Live alerts <span className="muted">({sim.unacknowledged} unacknowledged)</span>
        </h3>
      </div>
      <p className="muted small-note">
        Raised by the existing deterministic anomaly rules (prototype monitoring defaults) as observations arrive. Alerts are
        kept for this session only.
      </p>
      {alerts.some((a) => a.stale) && (
        <p className="alert alert-warning">The simulator connection closed; these alerts belong to the ended run.</p>
      )}
      {alerts.length === 0 ? (
        <p className="muted placeholder">No live alerts{sim.run ? ' so far in this run' : ''}.</p>
      ) : (
        <ol className="live-alert-list">
          {alerts.map((a) => (
            <li key={uid(a)} className={`live-alert ${a.acknowledged ? 'acknowledged' : ''}`} data-testid="live-alert">
              <div className="live-alert-row">
                <SeverityBadge severity={a.finding.severity} />
                <span className="live-alert-time">{hours(a.detected_at_hours)}</span>
                <button type="button" className="link-button" onClick={() => setOpenId(openId === uid(a) ? null : uid(a))} aria-expanded={openId === uid(a)}>
                  {a.finding.message}
                </button>
                {a.escalated && <span className="muted small-note">escalated</span>}
                {a.acknowledged ? (
                  <span className="muted small-note">acknowledged</span>
                ) : (
                  <button type="button" className="secondary small" onClick={() => sim.acknowledge(a.alert_id)}>
                    Acknowledge
                  </button>
                )}
              </div>
              {openId === uid(a) && <AlertDetail alert={a} explanation={explanations[uid(a)]} onExplain={() => explain(a)} />}
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
