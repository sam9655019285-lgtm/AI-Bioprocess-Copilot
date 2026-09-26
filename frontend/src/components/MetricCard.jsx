/** Single current-value tile (label, value, unit). Shows "—" when there is no value. */
export default function MetricCard({ label, value, unit, digits = 2, caption, className = '', missing = '—' }) {
  return (
    <div className={`metric ${className}`}>
      <div className="metric-label">{label}</div>
      <div className={`metric-value${value == null ? ' metric-value-missing' : ''}`}>
        {value == null ? missing : value.toFixed(digits)}
        <span className="metric-unit">{(value != null && unit) || '\u00a0'}</span>
      </div>
      {caption && <div className="metric-caption">{caption}</div>}
    </div>
  )
}
