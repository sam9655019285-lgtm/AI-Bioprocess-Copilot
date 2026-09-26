import { useState } from 'react'
import { findPrecedents } from '../api.js'

/*
 * Finding precedents (Phase 18): "Has the same rule been triggered before in our stored
 * experiments, and what did the stored data show afterwards?" A deterministic backend search
 * (POST /api/precedents/search) - exact rule matches only, no similarity or ranking, no Gemini.
 * Shared by the Live Alerts detail and the Anomalies page.
 */

const SEARCHABLE = new Set(['range', 'sudden_change', 'trend', 'co_occurrence'])

// Mirrors backend monitoring.alert_key (Python repr of the rounded culture time), used only to tell the
// server which finding is being investigated so it is never returned as its own precedent.
const pyFloat = (h) => {
  const r = Math.round(h * 10000) / 10000
  return Number.isInteger(r) ? r.toFixed(1) : String(r)
}
export function alertKeyFor(f) {
  if (f.type === 'range' || f.type === 'trend') return `${f.type}:${f.parameter}:${f.previous_time_hours == null ? '-' : pyFloat(f.previous_time_hours)}`
  if (f.type === 'sudden_change') return `change:${f.parameter}:${pyFloat(f.culture_time_hours)}`
  if (f.type === 'co_occurrence') return `cooccurrence:${pyFloat(f.culture_time_hours)}`
  return null
}

function queryFor(f) {
  if (f.type === 'co_occurrence') return { type: f.type, related_parameters: [...new Set(f.related_parameters)].sort() }
  return { type: f.type, parameter: f.parameter, direction: f.direction }
}

const hours = (t) => (t == null ? '—' : `${Number(t.toFixed(2))} h`)
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

function AfterCell({ p }) {
  const fu = p.follow_up
  return (
    <div className="prec-after">
      {fu.range_return && <div>{fu.range_return.note}</div>}
      {fu.values_at_window_end.map((v) => (
        <div key={v.parameter}>
          {v.label} at window end:{' '}
          {v.value == null ? 'no stored value' : `${v.value}${v.unit ? ` ${v.unit}` : ''} (${hours(v.culture_time_hours)})`}
        </div>
      ))}
      {fu.run_ended_before_window_end && (
        <div className="muted">Stored run ends before the {hours(fu.window_end_hours)} window end; nothing is extrapolated.</div>
      )}
      {fu.later_findings.length > 0 ? (
        <div>
          Later findings in window:{' '}
          {fu.later_findings.map((f) => `${f.type_label}${f.parameter_label ? ` (${f.parameter_label})` : ''} at ${hours(f.culture_time_hours)}`).join('; ')}
          {fu.later_findings_omitted > 0 && ` and ${fu.later_findings_omitted} more`}
        </div>
      ) : (
        <div className="muted">No later findings in the window.</div>
      )}
    </div>
  )
}

/**
 * `experimentId`/`alertId` identify the finding being investigated; `stored` says whether that
 * experiment is stored (enables "Compare with this run"); `onOpenComparison(a, b)` opens Comparison.
 */
export default function FindingPrecedents({ finding, experimentId, alertId, stored, onOpenComparison }) {
  const [state, setState] = useState(null) // { key, result } | { key, error } | { key, loading }
  if (!SEARCHABLE.has(finding.type)) return null
  const key = `${experimentId}|${alertId ?? alertKeyFor(finding)}`
  const shown = state?.key === key ? state : null

  async function search() {
    const query = { ...queryFor(finding), follow_up_hours: 12 }
    const id = alertId ?? alertKeyFor(finding)
    if (experimentId && id) query.current = { experiment_id: experimentId, alert_id: id }
    setState({ key, loading: true })
    try {
      setState({ key, result: await findPrecedents(query) })
    } catch (err) {
      setState({ key, error: err.message })
    }
  }

  const r = shown?.result
  return (
    <div className="precedents" data-testid="finding-precedents">
      <div className="prec-head">
        <button type="button" className="secondary small" onClick={search} disabled={shown?.loading}>
          {shown?.loading ? 'Searching…' : r ? 'Search again' : 'Find precedents'}
        </button>
        <span className="muted small-note">Same rule, parameter and direction in stored experiments (exact match; no AI).</span>
      </div>
      {shown?.error && <div className="alert alert-error">{shown.error}</div>}
      {r && (
        <div className="prec-result" data-testid="precedent-result">
          <p className="prec-summary">
            {r.precedents.length === 0
              ? `No matching findings in ${plural(r.experiments_searched, 'stored experiment')}.`
              : `${plural(r.precedents.length, 'matching finding')} in ${plural(r.matching_experiments, 'stored experiment')} (${r.experiments_searched} searched).`}
          </p>
          {r.experiments_skipped > 0 && (
            <p className="alert alert-warning">
              Only the {r.search_cap} most recently created experiments were searched; {r.experiments_skipped} older experiment(s) were not.
            </p>
          )}
          {r.precedents.length > 0 && (
            <>
              <p className="prec-legend">
                Run, time and severity <span className="cat-badge cat-observed">OBSERVED DATA</span> · afterwards (next{' '}
                {r.criteria.follow_up_hours} h) <span className="cat-badge cat-derived">DERIVED CALCULATION</span>
              </p>
              <div className="table-wrap">
                <table className="prec-table">
                  <thead>
                    <tr>
                      <th>Run</th>
                      <th>Scale</th>
                      <th>Time</th>
                      <th>Severity</th>
                      <th>What the stored data showed afterwards</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {r.precedents.map((p) => (
                      <tr key={`${p.experiment_id}|${p.trigger_time_hours}|${p.finding_type}`} data-testid="precedent-row">
                        <td>
                          <strong>{p.experiment_id}</strong>
                          <div className="muted">{p.name}</div>
                          <div className={p.same_run ? 'prec-relation prec-same' : 'prec-relation'}>{p.relation}</div>
                        </td>
                        <td className="num">{p.scale_liters} L</td>
                        <td className="num">{hours(p.trigger_time_hours)}</td>
                        <td>
                          <span className={`sev-badge sev-${p.severity}`}>{p.severity.toUpperCase()}</span>
                        </td>
                        <td>
                          <div className="prec-message">{p.message}</div>
                          <AfterCell p={p} />
                        </td>
                        <td>
                          {!p.same_run && (
                            <button
                              type="button"
                              className="secondary small"
                              disabled={!stored || !onOpenComparison}
                              title={stored ? '' : 'Available when the current run is saved to an experiment'}
                              onClick={() => onOpenComparison(experimentId, p.experiment_id)}
                            >
                              Compare with this run
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          <p className="muted small-note">{r.no_causation_note} Precedents show what was recorded, not what will happen in this run.</p>
        </div>
      )}
    </div>
  )
}
