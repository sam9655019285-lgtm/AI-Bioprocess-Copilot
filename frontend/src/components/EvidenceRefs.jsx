import { useId, useState } from 'react'

/*
 * Evidence-linked AI (Phase 21): compact references [F-001] to APPLICATION-generated evidence.
 * Only references that come with an evidence item from the backend are shown (the backend has
 * already removed unknown IDs); clicking one expands the deterministic fact inline. Presentation
 * only — no requests, no new navigation (the "View in …" button uses the existing onNavigate).
 */

const hours = (h) => (h == null ? null : `${Number(h.toFixed(2))} h`)
const num = (v) => (v == null ? null : Number(v.toFixed(4)).toString())

function span(item) {
  const a = hours(item.culture_time_start)
  const b = hours(item.culture_time_end)
  if (!a && !b) return null
  return a && b && a !== b ? `${a} – ${b}` : a || b
}

function shortLabel(item) {
  if (item.type === 'anomaly') return item.parameter_label ? `${item.parameter_label} · ${item.finding_type}` : item.finding_type
  if (item.type === 'data_coverage') return 'Data coverage'
  return item.parameter_label
}

function EvidenceDetail({ item, onNavigate }) {
  const unit = item.unit ? ` ${item.unit}` : ''
  const target = item.type === 'anomaly' ? ['anomalies', 'View in Anomalies'] : ['monitoring', 'View in Process Monitoring']
  const rows = [
    ['Parameter', item.parameter_label],
    ['Culture time', span(item)],
    item.type === 'anomaly'
      ? ['Observed change', item.previous_value != null && item.observed_value != null ? `${num(item.previous_value)} → ${num(item.observed_value)}${unit}` : num(item.observed_value) && `${num(item.observed_value)}${unit}`]
      : ['Start → final', item.previous_value != null ? `${num(item.previous_value)} → ${num(item.observed_value)}${unit}` : null],
    ['Range', item.minimum != null ? `${num(item.minimum)} – ${num(item.maximum)}${unit}` : null],
  ].filter(([, v]) => v)
  return (
    <div className={`evidence-detail evidence-${item.type}${item.severity ? ` evidence-sev-${item.severity}` : ''}`}>
      <div className="evidence-detail-head">
        <span className="evidence-detail-id">Evidence {item.id}</span>
        {item.type === 'anomaly' ? (
          <span className={`sev-badge sev-${item.severity}`}>{item.severity.toUpperCase()}</span>
        ) : item.type === 'process_statistic' ? (
          <span className="cat-badge cat-observed">OBSERVED DATA</span>
        ) : (
          <span className="cat-badge cat-derived">DERIVED CALCULATION</span>
        )}
      </div>
      <p className="evidence-detail-text">{item.description}</p>
      {rows.length > 0 && (
        <dl className="evidence-detail-facts">
          {rows.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="evidence-detail-foot">
        <span className="muted">
          Source: {item.source === 'deterministic_anomaly_detection' ? 'deterministic anomaly detection' : 'deterministic process analysis'} (application, not AI)
        </span>
        {onNavigate && (
          <button type="button" className="secondary small" onClick={() => onNavigate(target[0])}>
            {target[1]}
          </button>
        )}
      </div>
    </div>
  )
}

/** refs: evidence IDs cited by the AI; items: evidence objects returned by the backend. */
export default function EvidenceRefs({ label, refs = [], items = [], onNavigate }) {
  const [open, setOpen] = useState(null)
  const baseId = useId()
  const byId = Object.fromEntries(items.map((e) => [e.id, e]))
  const shown = refs.filter((r) => byId[r]) // never render an ID the backend did not supply
  if (shown.length === 0) return null
  const current = open && byId[open]
  return (
    <div className="evidence-refs">
      <span className="evidence-refs-label">{label}</span>
      <span className="evidence-ref-list">
        {shown.map((r) => (
          <button
            type="button"
            key={r}
            className={`evidence-ref evidence-${byId[r].type}${byId[r].severity ? ` evidence-sev-${byId[r].severity}` : ''}`}
            aria-expanded={open === r}
            aria-controls={`${baseId}-detail`}
            title={byId[r].description}
            onClick={() => setOpen(open === r ? null : r)}
          >
            <span className="evidence-ref-id">{r}</span>
            {shortLabel(byId[r]) && <span className="evidence-ref-name">{shortLabel(byId[r])}</span>}
          </button>
        ))}
      </span>
      <div id={`${baseId}-detail`}>{current && <EvidenceDetail item={current} onNavigate={onNavigate} />}</div>
    </div>
  )
}

/** Note when the AI cited IDs the application never supplied (they were removed by the backend). */
export function RejectedRefsNote({ refs = [] }) {
  if (refs.length === 0) return null
  return (
    <p className="muted small-note evidence-rejected">
      {refs.length} evidence reference(s) returned by the AI did not match any application evidence and were removed.
    </p>
  )
}
