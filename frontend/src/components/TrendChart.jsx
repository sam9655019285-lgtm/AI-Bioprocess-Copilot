import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

const AXIS_TICK = { fill: 'var(--muted)', fontSize: 12 }

/**
 * Y scale with round-number ticks, at least `minSpan` tall so small noise on a
 * stable signal doesn't fill the whole chart.
 */
function yScale(data, dataKey, minSpan) {
  const values = data.map((d) => d[dataKey])
  let lo = Math.min(...values)
  let hi = Math.max(...values)
  if (hi - lo < minSpan) {
    const mid = (lo + hi) / 2
    lo = mid - minSpan / 2
    hi = mid + minSpan / 2
  }
  const rough = (hi - lo) / 4
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  const step = +([1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rough)).toPrecision(2)
  const decimals = (String(step).split('.')[1] ?? '').length
  const ticks = []
  for (let v = Math.floor(lo / step) * step; ; v += step) {
    ticks.push(+v.toFixed(decimals))
    if (v >= hi - step * 1e-6) break
  }
  return { domain: [ticks[0], ticks.at(-1)], ticks, decimals }
}

export default function TrendChart({ title, unit, dataKey, data, digits = 2, minSpan = 1 }) {
  const format = (v) => v.toFixed(digits)
  const y = yScale(data, dataKey, minSpan)
  return (
    <figure className="trend">
      <figcaption>
        {title} {unit && <span className="muted">({unit})</span>}
      </figcaption>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis
            dataKey="culture_time_hours"
            type="number"
            domain={['dataMin', 'dataMax']}
            allowDecimals={false}
            tick={AXIS_TICK}
            tickFormatter={(v) => `${Math.round(v)} h`}
            stroke="var(--border)"
          />
          <YAxis
            domain={y.domain}
            ticks={y.ticks}
            tick={AXIS_TICK}
            tickFormatter={(v) => v.toFixed(y.decimals)}
            width={52}
            stroke="var(--border)"
          />
          <Tooltip
            formatter={(v) => [`${format(v)} ${unit}`.trim(), title]}
            labelFormatter={(t) => `Culture time ${t} h`}
            contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6 }}
            labelStyle={{ color: 'var(--muted)' }}
            itemStyle={{ color: 'var(--text)' }}
            cursor={{ stroke: 'var(--muted)', strokeDasharray: '3 3' }}
          />
          <Line
            dataKey={dataKey}
            stroke="var(--series)"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </figure>
  )
}
