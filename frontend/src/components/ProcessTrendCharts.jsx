import TrendChart from './TrendChart.jsx'

// Chart order and minimum y-span per parameter (display only). Optional parameters last.
const CHARTS = [
  { parameter: 'temperature_c', minSpan: 1 },
  { parameter: 'ph', minSpan: 0.2 },
  { parameter: 'dissolved_oxygen_percent', minSpan: 10 },
  { parameter: 'cell_density', minSpan: 1 },
  { parameter: 'agitation_rpm', minSpan: 20 },
  { parameter: 'feed_rate', minSpan: 1 },
  { parameter: 'nutrient_concentration', minSpan: 1 },
  { parameter: 'aeration_rate', minSpan: 0.05 },
]

/**
 * One chart per parameter vs culture time, only for parameters with at least two values
 * (optional parameters are often partly or entirely missing).
 */
export default function ProcessTrendCharts({ observations, parameters }) {
  const byName = Object.fromEntries(parameters.map((p) => [p.parameter, p]))
  const charts = CHARTS.filter((c) => byName[c.parameter]?.count >= 2)

  return (
    <div className="charts">
      {charts.map(({ parameter, minSpan }) => {
        const p = byName[parameter]
        return (
          <TrendChart
            key={parameter}
            title={p.label}
            unit={p.unit ?? ''}
            dataKey={parameter}
            data={observations.filter((o) => o[parameter] != null)}
            digits={p.decimals}
            minSpan={minSpan}
          />
        )
      })}
    </div>
  )
}
