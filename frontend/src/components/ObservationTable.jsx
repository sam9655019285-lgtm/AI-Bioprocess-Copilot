export default function ObservationTable({ title, fields, observations }) {
  return (
    <div className="table-wrap">
      <table>
        <caption>{title}</caption>
        <thead>
          <tr>
            {fields.map((f) => (
              <th key={f.name}>
                {f.label}
                {f.unit && <span className="th-unit"> ({f.unit})</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {observations.map((obs, i) => (
            <tr key={i}>
              {fields.map((f) => (
                <td key={f.name} className={f.type === 'number' ? 'num' : undefined}>
                  {obs[f.name] ?? '—'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
