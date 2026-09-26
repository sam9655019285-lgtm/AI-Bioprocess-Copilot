import { memo } from 'react'

/*
 * Illustrative stirred-tank drawing driven only by the latest simulator observation.
 * The mapping functions below turn simulator values into animation parameters; they are
 * visual scalings, not physical models (no kLa, CFD or growth model).
 */

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))

/** Seconds per visual impeller revolution; null = stopped (rpm missing or 0). */
export const impellerPeriod = (rpm) => (rpm > 0 ? clamp(90 / rpm, 0.25, 6) : null)
/** Number of rising bubbles for an aeration rate in vvm; 0 = no gas flow. */
export const bubbleCount = (vvm) => (vvm > 0 ? clamp(Math.round(vvm * 80), 2, 18) : 0)
/** Seconds for a bubble to rise; more gas flow = faster. */
export const bubbleDuration = (vvm) => clamp(3.2 - vvm * 4, 1.2, 3.2)
/** Illustrative cell particles for a density in ×10⁶ cells/mL (capped; not a literal cell count). */
export const MAX_CELL_PARTICLES = 100
export const cellCount = (density) => (density > 0 ? clamp(Math.round(density * 8), 1, MAX_CELL_PARTICLES) : 0)
/** Seconds between feed drops; null = no feed (missing or 0). */
export const feedPeriod = (mlPerHour) => (mlPerHour > 0 ? clamp(4 / mlPerHour, 0.5, 3) : null)
/** Thermometer fill on a fixed 20–45 °C display scale (the simulator's allowed start range). */
export const THERMO_MIN = 20
export const THERMO_MAX = 45
const thermoFraction = (t) => (t == null ? 0 : clamp((t - THERMO_MIN) / (THERMO_MAX - THERMO_MIN), 0, 1))

// Drawing geometry (viewBox units)
const LIQUID_TOP = 132
const LIQUID_BOTTOM = 352
const LEFT = 74
const RIGHT = 246
const SHAFT_X = 160
const IMPELLER_Y = 296
const SPARGER_Y = 334

// Deterministic, evenly spread particle positions (golden-ratio sequence), avoiding the shaft.
const CELL_POSITIONS = Array.from({ length: MAX_CELL_PARTICLES }, (_, i) => {
  const fx = (i * 0.618034 + 0.13) % 1
  const fy = (i * 0.414214 + 0.27) % 1
  let x = LEFT + 10 + fx * (RIGHT - LEFT - 20)
  if (Math.abs(x - SHAFT_X) < 9) x += x < SHAFT_X ? -9 : 9
  return { x, y: LIQUID_TOP + 12 + fy * (LIQUID_BOTTOM - LIQUID_TOP - 26), drift: i % 4 }
})

const Cells = memo(function Cells({ count }) {
  return (
    <g className="bx-cells" data-testid="bx-cells" data-count={count}>
      <title>Cell density: simulated viable cell concentration (illustrative particles)</title>
      {CELL_POSITIONS.slice(0, count).map((p, i) => (
        <circle key={i} className={`bx-cell drift-${p.drift}`} cx={p.x} cy={p.y} r={2.6} />
      ))}
    </g>
  )
})

const Bubbles = memo(function Bubbles({ count, duration }) {
  return (
    <g className="bx-bubbles" data-testid="bx-bubbles" data-count={count}>
      <title>Aeration: gas flow into the reactor (illustrative bubbles)</title>
      {Array.from({ length: count }, (_, i) => {
        const x = SHAFT_X - 34 + ((i * 37) % 68)
        return (
          <circle
            key={i}
            className="bx-bubble"
            cx={x}
            cy={SPARGER_Y - 4}
            r={2 + (i % 3)}
            style={{ animationDuration: `${duration}s`, animationDelay: `${-((i * duration) / count).toFixed(2)}s` }}
          />
        )
      })}
    </g>
  )
})

function BioreactorVessel({ values, running, volumeLiters }) {
  const { temperature_c: temp, agitation_rpm: rpm, aeration_rate: vvm, feed_rate: feed, cell_density: cells } = values ?? {}
  const period = impellerPeriod(rpm)
  const bubbles = bubbleCount(vvm)
  const feedEvery = feedPeriod(feed)
  const hasData = Boolean(values)
  const thermoHeight = 150 * thermoFraction(temp)

  return (
    <svg
      viewBox="0 0 330 430"
      className={`bioreactor-svg ${running ? 'running' : 'paused'}`}
      role="img"
      aria-label={`Illustrative stirred-tank bioreactor. ${running ? 'Simulation running.' : 'Simulation not running.'}`}
    >
      {/* motor + shaft */}
      <rect x={SHAFT_X - 16} y={14} width={32} height={22} rx={4} className="bx-metal" />
      <text x={SHAFT_X + 22} y={29} className="bx-label">Motor</text>
      <line x1={SHAFT_X} y1={36} x2={SHAFT_X} y2={IMPELLER_Y} className="bx-shaft" />

      {/* temperature jacket + vessel */}
      <rect x={LEFT - 12} y={92} width={RIGHT - LEFT + 24} height={286} rx={34} className="bx-jacket">
        <title>Temperature jacket (illustrative)</title>
      </rect>
      <rect x={LEFT} y={84} width={RIGHT - LEFT} height={286} rx={26} className="bx-vessel" />
      <line x1={LEFT - 6} y1={84} x2={RIGHT + 6} y2={84} className="bx-headplate" />

      {/* liquid */}
      <path
        d={`M${LEFT + 1} ${LIQUID_TOP} H${RIGHT - 1} V${LIQUID_BOTTOM - 6} Q${RIGHT - 1} 368 ${RIGHT - 26} 368 H${LEFT + 26} Q${LEFT + 1} 368 ${LEFT + 1} ${LIQUID_BOTTOM - 6} Z`}
        className={`bx-liquid ${hasData ? '' : 'empty'}`}
      >
        <title>Culture medium</title>
      </path>
      <line x1={LEFT + 1} y1={LIQUID_TOP} x2={RIGHT - 1} y2={LIQUID_TOP} className="bx-surface" />

      {/* mixing indicators */}
      <g className={`bx-mixing ${period ? 'on' : ''}`} data-testid="bx-mixing" style={period ? { '--mix-period': `${(period * 6).toFixed(2)}s` } : undefined}>
        <title>Agitation: controls mixing (illustrative flow)</title>
        <path d={`M${SHAFT_X - 24} ${IMPELLER_Y - 6} C ${LEFT + 6} ${IMPELLER_Y - 10}, ${LEFT + 8} ${LIQUID_TOP + 30}, ${SHAFT_X - 30} ${LIQUID_TOP + 34}`} className="bx-flow" />
        <path d={`M${SHAFT_X + 24} ${IMPELLER_Y - 6} C ${RIGHT - 6} ${IMPELLER_Y - 10}, ${RIGHT - 8} ${LIQUID_TOP + 30}, ${SHAFT_X + 30} ${LIQUID_TOP + 34}`} className="bx-flow" />
      </g>

      {hasData && <Cells count={cellCount(cells)} />}

      {/* probes */}
      <line x1={112} y1={70} x2={112} y2={200} className="bx-probe" />
      <text x={100} y={66} className="bx-label">pH</text>
      <line x1={208} y1={70} x2={208} y2={200} className="bx-probe" />
      <text x={200} y={66} className="bx-label">DO</text>

      {/* impeller (side view: blades narrow and widen as they turn) */}
      <g
        className={`bx-impeller ${period ? 'spinning' : ''}`}
        data-testid="bx-impeller"
        data-period={period ?? ''}
        style={period ? { '--impeller-period': `${period.toFixed(2)}s` } : undefined}
      >
        <title>Impeller: agitation (mixing)</title>
        <rect x={SHAFT_X - 30} y={IMPELLER_Y - 7} width={60} height={14} rx={3} className="bx-blades" />
        <rect x={SHAFT_X - 5} y={IMPELLER_Y - 9} width={10} height={18} rx={2} className="bx-metal" />
      </g>

      {/* gas inlet, sparger, bubbles */}
      <path d={`M14 404 H${SHAFT_X - 44} V${SPARGER_Y}`} className="bx-pipe" />
      <line x1={SHAFT_X - 44} y1={SPARGER_Y} x2={SHAFT_X + 44} y2={SPARGER_Y} className="bx-sparger" />
      <text x={14} y={398} className="bx-label">Gas in (air/O₂)</text>
      {bubbles > 0 && <Bubbles count={bubbles} duration={bubbleDuration(vvm)} />}

      {/* gas outlet */}
      <path d={`M232 84 V46 H300`} className="bx-pipe" />
      <text x={258} y={40} className="bx-label">Gas out</text>
      {bubbles > 0 && <path d={`M232 80 V46 H300`} className="bx-gas-out" />}

      {/* feed line */}
      <path d={`M12 58 H94 V112`} className="bx-pipe" />
      <text x={12} y={52} className="bx-label">Feed</text>
      <g className="bx-feed" data-testid="bx-feed" data-active={feedEvery ? 'true' : 'false'}>
        <title>Feed: nutrient/media addition</title>
        {feedEvery &&
          [0, 1, 2].map((i) => (
            <circle
              key={i}
              className="bx-drop"
              cx={94}
              cy={116}
              r={2.6}
              style={{ animationDuration: `${feedEvery}s`, animationDelay: `${-(i * feedEvery) / 3}s` }}
            />
          ))}
      </g>

      {/* thermometer */}
      <g aria-hidden="true">
        <rect x={296} y={150} width={10} height={156} rx={5} className="bx-thermo-tube" />
        <rect x={298} y={304 - thermoHeight} width={6} height={thermoHeight} rx={3} className="bx-thermo-fill" data-testid="bx-thermo" />
        <circle cx={301} cy={314} r={10} className="bx-thermo-bulb" />
        <text x={288} y={342} className="bx-label">{THERMO_MIN}–{THERMO_MAX} °C</text>
      </g>

      <text x={SHAFT_X} y={424} textAnchor="middle" className="bx-label">
        Working volume {volumeLiters ? `${volumeLiters} L` : 'not set'} · drawing not to scale
      </text>
    </svg>
  )
}

export default memo(BioreactorVessel)
