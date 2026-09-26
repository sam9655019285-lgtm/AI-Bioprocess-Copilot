/** Format for display only; the underlying values stay unrounded. */
export function formatValue(value, decimals, { signed = false } = {}) {
  const text = value.toFixed(decimals)
  if (Number(text) === 0) return (0).toFixed(decimals) // avoid "-0.00"
  return signed && value > 0 ? `+${text}` : text
}

/** Start / final / min / max / average / delta per parameter, as returned by the analysis API. */
export default function ProcessStatistics({ parameters }) {
  return (
    <div className="table-wrap">
      <table className="stats-table">
        <thead>
          <tr>
            <th>Parameter</th>
            <th>Start</th>
            <th>Final</th>
            <th>Min</th>
            <th>Max</th>
            <th>Average</th>
            <th>Delta</th>
            <th title="Observations with a value">n</th>
          </tr>
        </thead>
        <tbody>
          {parameters.map((p) => (
            <tr key={p.parameter}>
              <td>
                {p.label}
                {p.unit && <span className="th-unit"> ({p.unit})</span>}
                {!p.required && <span className="muted"> · optional</span>}
              </td>
              <td className="num">{formatValue(p.start, p.decimals)}</td>
              <td className="num">{formatValue(p.final, p.decimals)}</td>
              <td className="num">{formatValue(p.minimum, p.decimals)}</td>
              <td className="num">{formatValue(p.maximum, p.decimals)}</td>
              <td className="num">{formatValue(p.average, p.decimals + 1)}</td>
              <td className="num">{formatValue(p.delta, p.decimals, { signed: true })}</td>
              <td className="num">{p.count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
