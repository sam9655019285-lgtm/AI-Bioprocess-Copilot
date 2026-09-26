import { useEffect, useState } from 'react'
import { modelScaleUp } from '../api.js'

/*
 * Advanced Scale-Up Modeling (Phase 14): shows the backend's illustrative engineering
 * estimates (POST /api/scale-up/model). All calculations happen in the backend; this
 * component only collects assumptions and displays labelled results.
 */

const CATEGORY_CLASS = {
  'OBSERVED DATA': 'cat-observed',
  'DERIVED CALCULATION': 'cat-derived',
  'MODEL ASSUMPTION': 'cat-assumption',
  'SCENARIO RESULT': 'cat-scenario',
  'NOT AVAILABLE': 'cat-na',
}
const DEFAULTS = {
  source_impeller_diameter_m: '',
  target_impeller_diameter_m: '',
  power_number: '5',
  liquid_density_kg_m3: '1000',
  q_o2_pmol_per_cell_h: '0.2',
  oxygen_saturation_mmol_l: '0.21',
  k: '5',
  a: '0.4',
  b: '0.5',
}
const INPUTS = [
  { key: 'source_impeller_diameter_m', label: 'Source impeller diameter', unit: 'm' },
  { key: 'target_impeller_diameter_m', label: 'Target impeller diameter', unit: 'm' },
  { key: 'power_number', label: 'Power number Np', unit: '' },
  { key: 'liquid_density_kg_m3', label: 'Liquid density ρ', unit: 'kg/m³' },
  { key: 'q_o2_pmol_per_cell_h', label: 'Specific O₂ uptake qO2', unit: 'pmol/cell/h' },
  { key: 'oxygen_saturation_mmol_l', label: 'O₂ saturation C*', unit: 'mmol/L' },
  { key: 'k', label: 'kLa constant K', unit: '1/h' },
  { key: 'a', label: 'kLa exponent a', unit: '' },
  { key: 'b', label: 'kLa exponent b', unit: '' },
]
const FORMULAS = [
  'P/V = Np · ρ · N³ · D⁵ / V',
  'Tip speed = π · D · N',
  'kLa = K · (P/V)^a · vvm^b',
  'OTR = kLa · (C* − C),  C = DO% / 100 · C*',
  'OUR = qO2 · X',
]

const fmt = (v, unit, d = 3) =>
  v == null ? 'Not available' : `${v.toLocaleString('en-US', { maximumSignificantDigits: 4, maximumFractionDigits: d })}${unit && unit !== '-' ? ` ${unit}` : ''}`

function Badge({ category }) {
  return <span className={`cat-badge ${CATEGORY_CLASS[category] ?? ''}`}>{category}</span>
}

function QuantityCard({ q, title }) {
  return (
    <div className="metric adv-card" data-testid={`adv-${title}`}>
      <div className="metric-label">{q.label}</div>
      <div className="metric-value">{fmt(q.value, '')}</div>
      <div className="metric-unit">{q.value == null ? ' ' : q.unit}</div>
      <Badge category={q.category} />
      {q.formula && <div className="metric-caption">{q.formula}</div>}
      {q.note && q.value == null && <div className="metric-caption">{q.note}</div>}
    </div>
  )
}

export default function AdvancedScaleUpModeling({ experimentId, targetScale }) {
  const [inputs, setInputs] = useState(DEFAULTS)
  const [agitation, setAgitation] = useState('constant_pv')
  const [aeration, setAeration] = useState('constant_vvm')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const target = Number(targetScale)

  useEffect(() => {
    if (!experimentId || !(target > 0)) return
    const body = {
      source_experiment_id: experimentId,
      target_scale_liters: target,
      power_number: Number(inputs.power_number),
      liquid_density_kg_m3: Number(inputs.liquid_density_kg_m3),
      q_o2_pmol_per_cell_h: Number(inputs.q_o2_pmol_per_cell_h),
      oxygen_saturation_mmol_l: Number(inputs.oxygen_saturation_mmol_l),
      constants: { k: Number(inputs.k), a: Number(inputs.a), b: Number(inputs.b) },
      agitation_strategy: agitation,
      aeration_strategy: aeration,
    }
    for (const key of ['source_impeller_diameter_m', 'target_impeller_diameter_m']) {
      if (inputs[key].trim() !== '') body[key] = Number(inputs[key])
    }
    let cancelled = false
    const timer = setTimeout(() => {
      setLoading(true)
      modelScaleUp(body)
        .then((r) => {
          if (cancelled) return
          setResult(r)
          setError(null)
        })
        .catch((err) => !cancelled && setError(err.message))
        .finally(() => !cancelled && setLoading(false))
    }, 300)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [experimentId, target, inputs, agitation, aeration])

  function exampleGeometry() {
    // Geometric similarity example: D ∝ V^(1/3). A labelled assumption, not measured geometry.
    const source = result?.source_scale_liters ?? 1
    const ds = 0.05 * Math.cbrt(source)
    const dt = ds * Math.cbrt(target / source)
    setInputs((v) => ({ ...v, source_impeller_diameter_m: ds.toFixed(4), target_impeller_diameter_m: dt.toFixed(4) }))
  }

  const r = result?.experiment_id === experimentId ? result : null
  const rows = r?.strategy_comparison ?? []

  return (
    <section className="adv-model" aria-label="Advanced Scale-Up Modeling">
      <h3>Advanced Scale-Up Modeling</h3>
      <div className="alert alert-warning adv-note">
        <strong>Engineering estimate — model assumptions are configurable.</strong>{' '}
        {r?.disclaimer ??
          'These calculations are illustrative engineering estimates and do not replace experimentally validated bioreactor design or process-development data.'}
      </div>
      <ul className="adv-formulas">
        {FORMULAS.map((f) => (
          <li key={f}>
            <code>{f}</code>
          </li>
        ))}
      </ul>

      <div className="card-header scenario-header">
        <h4>Model assumptions</h4>
        <div className="actions">
          <button type="button" className="secondary small" onClick={exampleGeometry}>
            Use example geometry (D ∝ V^1/3)
          </button>
          <button type="button" className="secondary small" onClick={() => setInputs(DEFAULTS)}>
            Reset assumptions
          </button>
        </div>
      </div>
      <p className="muted small-note">
        Impeller diameters are not assumed: leave them empty and geometry-based results show “Not available”. The example
        geometry button fills a labelled geometric-similarity assumption.
      </p>
      <div className="config-grid">
        {INPUTS.map((f) => (
          <label key={f.key} className="field">
            <span>{f.label}</span>
            <span className="input-with-unit">
              <input
                name={`adv-${f.key}`}
                type="number"
                step="any"
                value={inputs[f.key]}
                onChange={(e) => setInputs((v) => ({ ...v, [f.key]: e.target.value }))}
              />
              {f.unit && <span className="unit">{f.unit}</span>}
            </span>
          </label>
        ))}
        <label className="field">
          <span>Agitation strategy</span>
          <select value={agitation} onChange={(e) => setAgitation(e.target.value)} name="adv-agitation">
            <option value="constant_rpm">Constant RPM</option>
            <option value="constant_tip_speed">Constant tip speed</option>
            <option value="constant_pv">Constant P/V</option>
          </select>
        </label>
        <label className="field">
          <span>Aeration strategy</span>
          <select value={aeration} onChange={(e) => setAeration(e.target.value)} name="adv-aeration">
            <option value="constant_vvm">Constant vvm</option>
            <option value="constant_gas_flow">Constant gas flow</option>
          </select>
        </label>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {loading && !r && <p className="muted">Calculating…</p>}
      {r && (
        <>
          {['source', 'target'].map((side) => (
            <div key={side}>
              <h4 className="adv-side">
                {side === 'source' ? `Source (${fmt(r.source_scale_liters, 'L')})` : `Target scenario (${fmt(r.target_scale_liters, 'L')})`}
              </h4>
              <div className="metrics adv-cards">
                {['kla_per_h', 'power_per_volume_w_m3', 'tip_speed_m_s', 'otr_mmol_l_h', 'our_mmol_l_h', 'rpm', 'gas_flow_l_min'].map((k) => (
                  <QuantityCard key={k} q={r[side][k]} title={`${side}-${k}`} />
                ))}
                <div className="metric adv-card" data-testid={`adv-${side}-balance`}>
                  <div className="metric-label">Oxygen balance (OTR − OUR)</div>
                  <div className="metric-value">{fmt(r[`oxygen_balance_${side}`].difference_mmol_l_h, '')}</div>
                  <div className="metric-unit">{r[`oxygen_balance_${side}`].difference_mmol_l_h == null ? ' ' : 'mmol/L/h'}</div>
                  <Badge category={r[`oxygen_balance_${side}`].category} />
                  <div className="metric-caption">{r[`oxygen_balance_${side}`].state}</div>
                </div>
              </div>
            </div>
          ))}

          <h4>Strategy comparison</h4>
          <p className="muted small-note">Strategies are not ranked; compare them against process knowledge and experimental data.</p>
          <div className="table-wrap">
            <table className="adv-table" data-testid="adv-strategies">
              <thead>
                <tr>
                  <th>Strategy</th>
                  <th>Parameter</th>
                  <th>Source</th>
                  <th>Target</th>
                  <th>Change</th>
                  <th>Formula</th>
                  <th>Assumption</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((x) => (
                  <tr key={`${x.strategy}-${x.parameter}`} className={x.strategy === agitation || x.strategy === aeration ? 'row-selected' : undefined}>
                    <td>{x.label}</td>
                    <td>{x.parameter}</td>
                    <td className="num">{fmt(x.source, x.unit)}</td>
                    <td className="num">{fmt(x.target, x.unit)}</td>
                    <td className="num">{x.change == null ? '—' : fmt(x.change, x.unit)}</td>
                    <td>
                      <code>{x.formula}</code>
                    </td>
                    <td className="wrap">{x.assumption}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h4>Observed inputs and assumptions</h4>
          <div className="table-wrap">
            <table>
              <tbody>
                {[...r.observed, ...r.assumptions].map((q) => (
                  <tr key={q.label}>
                    <td>{q.label}</td>
                    <td className="num">{fmt(q.value, q.unit)}</td>
                    <td>
                      <Badge category={q.category} />
                    </td>
                    <td className="wrap muted">{q.note ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="summary-list">
            {r.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
