"""Advanced scale-up modeling (Phase 14): illustrative engineering estimates.

These calculations are illustrative engineering estimates and do not replace experimentally
validated bioreactor design or process-development data. The module is not a validated
industrial bioreactor model: every constant is a configurable MODEL ASSUMPTION, vessel
geometry is never invented (without impeller diameters the geometry-based quantities are
NOT AVAILABLE), and nothing is stored.

Formulas (SI inside, displayed units in results):
  P      = Np · rho · N³ · D⁵                 [W]    N in rev/s, D in m, rho in kg/m³
  P/V    = P / V                              [W/m³] V in m³
  tip    = π · D · N                          [m/s]
  kLa    = K · (P/V)^a · vvm^b                [1/h]  (empirical form; K, a, b assumed)
  C      = DO% / 100 · C*                     [mmol/L] (DO concentration conversion assumption)
  OTR    = kLa · (C* − C)                     [mmol/L/h]
  OUR    = qO2 · X                            [mmol/L/h] qO2 in pmol/cell/h, X in 10⁶ cells/mL
  constant tip speed: N_t = N_s · D_s / D_t
  constant P/V:       N_t = N_s · (D_s/D_t)^(5/3) · (V_t/V_s)^(1/3)
  constant vvm:       Q_t = vvm · V_t;  constant gas flow: Q_t = Q_s
"""

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from . import repository as repo
from .analysis import summarize_parameter
from .db_models import ExperimentRow

DISCLAIMER = (
    "These calculations are illustrative engineering estimates and do not replace experimentally validated "
    "bioreactor design or process-development data. The advanced scale-up module is not a validated industrial "
    "bioreactor model."
)
BALANCE_TOLERANCE = 0.10  # |OTR - OUR| within 10 % of the larger value -> "approximately balanced"

OBSERVED = "OBSERVED DATA"
DERIVED = "DERIVED CALCULATION"
ASSUMPTION = "MODEL ASSUMPTION"
SCENARIO = "SCENARIO RESULT"
NOT_AVAILABLE = "NOT AVAILABLE"

AgitationStrategy = Literal["constant_rpm", "constant_tip_speed", "constant_pv"]
AerationStrategy = Literal["constant_vvm", "constant_gas_flow"]
STRATEGY_LABELS = {
    "constant_rpm": "Constant RPM", "constant_tip_speed": "Constant tip speed", "constant_pv": "Constant P/V",
    "constant_vvm": "Constant vvm", "constant_gas_flow": "Constant gas flow",
}


class ModelConstants(BaseModel):
    model_config = ConfigDict(extra="forbid")
    k: float = Field(default=5.0, gt=0, allow_inf_nan=False, description="kLa prefactor K (assumed)")
    a: float = Field(default=0.4, gt=0, le=2, allow_inf_nan=False, description="P/V exponent a (assumed)")
    b: float = Field(default=0.5, gt=0, le=2, allow_inf_nan=False, description="vvm exponent b (assumed)")


class ScaleUpModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_experiment_id: str = Field(min_length=1, max_length=100)
    target_scale_liters: float = Field(gt=0, le=1_000_000, allow_inf_nan=False)
    source_impeller_diameter_m: float | None = Field(default=None, gt=0, le=10, allow_inf_nan=False)
    target_impeller_diameter_m: float | None = Field(default=None, gt=0, le=10, allow_inf_nan=False)
    power_number: float = Field(default=5.0, gt=0, le=20, allow_inf_nan=False)
    liquid_density_kg_m3: float = Field(default=1000.0, gt=0, le=3000, allow_inf_nan=False)
    q_o2_pmol_per_cell_h: float = Field(default=0.2, ge=0, le=10, allow_inf_nan=False)
    oxygen_saturation_mmol_l: float = Field(default=0.21, gt=0, le=10, allow_inf_nan=False)
    constants: ModelConstants = ModelConstants()
    agitation_strategy: AgitationStrategy = "constant_pv"
    aeration_strategy: AerationStrategy = "constant_vvm"


class Quantity(BaseModel):
    label: str
    value: float | None
    unit: str
    category: str  # OBSERVED DATA | DERIVED CALCULATION | MODEL ASSUMPTION | SCENARIO RESULT | NOT AVAILABLE
    formula: str | None = None
    note: str | None = None


class ConditionSet(BaseModel):
    """Engineering quantities at one scale (source or target scenario)."""

    volume_l: float
    rpm: Quantity
    vvm: Quantity
    gas_flow_l_min: Quantity
    power_per_volume_w_m3: Quantity
    tip_speed_m_s: Quantity
    kla_per_h: Quantity
    otr_mmol_l_h: Quantity
    our_mmol_l_h: Quantity


class OxygenBalance(BaseModel):
    otr_mmol_l_h: float | None
    our_mmol_l_h: float | None
    difference_mmol_l_h: float | None
    state: str
    category: str


class StrategyRow(BaseModel):
    strategy: str
    label: str
    parameter: str
    unit: str
    source: float | None
    target: float | None
    change: float | None
    formula: str
    assumption: str
    category: str


class ScaleUpModelResult(BaseModel):
    label: str = "Engineering estimate"
    disclaimer: str = DISCLAIMER
    experiment_id: str
    source_scale_liters: float
    target_scale_liters: float
    observed: list[Quantity]
    assumptions: list[Quantity]
    source: ConditionSet
    target: ConditionSet
    oxygen_balance_source: OxygenBalance
    oxygen_balance_target: OxygenBalance
    agitation_strategy: AgitationStrategy
    aeration_strategy: AerationStrategy
    strategy_comparison: list[StrategyRow]  # no ranking; the user decides
    notes: list[str]


class ScaleUpModelError(ValueError):
    pass


# --- pure calculations (None-safe; None means "not available") ------------------------------

def power_w(np_: float, rho: float, rpm: float | None, d: float | None) -> float | None:
    if rpm is None or d is None:
        return None
    return np_ * rho * (rpm / 60) ** 3 * d ** 5


def power_per_volume(np_: float, rho: float, rpm: float | None, d: float | None, volume_l: float) -> float | None:
    p = power_w(np_, rho, rpm, d)
    return None if p is None else p / (volume_l / 1000)


def tip_speed(rpm: float | None, d: float | None) -> float | None:
    return None if rpm is None or d is None else math.pi * d * rpm / 60


def kla(c: ModelConstants, pv: float | None, vvm: float | None) -> float | None:
    if pv is None or vvm is None:
        return None
    return c.k * pv ** c.a * vvm ** c.b  # 0 when there is no power or no gas


def otr(kla_h: float | None, c_star: float, do_percent: float | None) -> float | None:
    if kla_h is None or do_percent is None:
        return None
    return kla_h * (c_star - do_percent / 100 * c_star)


def our(q_o2: float, cells_1e6_per_ml: float | None) -> float | None:
    return None if cells_1e6_per_ml is None else q_o2 * cells_1e6_per_ml


def oxygen_balance(otr_v: float | None, our_v: float | None) -> OxygenBalance:
    if otr_v is None or our_v is None:
        return OxygenBalance(otr_mmol_l_h=otr_v, our_mmol_l_h=our_v, difference_mmol_l_h=None,
                             state="Not available: OTR or OUR cannot be estimated from the available data.",
                             category=NOT_AVAILABLE)
    diff = otr_v - our_v
    scale = max(abs(otr_v), abs(our_v))
    if scale == 0 or abs(diff) <= BALANCE_TOLERANCE * scale:
        state = "Approximately balanced"
    elif diff > 0:
        state = "Estimated transfer capacity exceeds estimated uptake"
    else:
        state = "Estimated uptake exceeds estimated transfer capacity"
    return OxygenBalance(otr_mmol_l_h=otr_v, our_mmol_l_h=our_v, difference_mmol_l_h=diff, state=state, category=DERIVED)


def target_rpm(strategy: str, rpm_s: float | None, d_s: float | None, d_t: float | None,
               v_s: float, v_t: float) -> float | None:
    if rpm_s is None:
        return None
    if strategy == "constant_rpm":
        return rpm_s
    if d_s is None or d_t is None:
        return None
    if strategy == "constant_tip_speed":
        return rpm_s * d_s / d_t
    return rpm_s * (d_s / d_t) ** (5 / 3) * (v_t / v_s) ** (1 / 3)  # constant P/V


def target_aeration(strategy: str, vvm_s: float | None, v_s: float, v_t: float) -> tuple[float | None, float | None]:
    """(target vvm, target gas flow L/min)."""
    if vvm_s is None:
        return None, None
    if strategy == "constant_vvm":
        return vvm_s, vvm_s * v_t
    q_s = vvm_s * v_s
    return q_s / v_t, q_s  # constant gas flow


# --- assembly ------------------------------------------------------------------------------

def _q(label, value, unit, category, formula=None, note=None) -> Quantity:
    return Quantity(label=label, value=value, unit=unit, category=category if value is not None else NOT_AVAILABLE,
                    formula=formula, note=note)


def _conditions(req, volume_l, rpm_v, rpm_cat, vvm_v, vvm_cat, d, do, cells, category) -> ConditionSet:
    pv = power_per_volume(req.power_number, req.liquid_density_kg_m3, rpm_v, d, volume_l)
    k = kla(req.constants, pv, vvm_v)
    geometry = None if d is not None else "Impeller diameter not supplied (geometry is not assumed)."
    return ConditionSet(
        volume_l=volume_l,
        rpm=_q("Agitation", rpm_v, "rpm", rpm_cat),
        vvm=_q("Aeration", vvm_v, "vvm", vvm_cat),
        gas_flow_l_min=_q("Gas flow", None if vvm_v is None else vvm_v * volume_l, "L/min", category, "Q = vvm × V"),
        power_per_volume_w_m3=_q("Power per volume", pv, "W/m³", category, "P/V = Np·ρ·N³·D⁵ / V", geometry),
        tip_speed_m_s=_q("Impeller tip speed", tip_speed(rpm_v, d), "m/s", category, "tip = π·D·N", geometry),
        kla_per_h=_q("kLa (estimated)", k, "1/h", category, "kLa = K·(P/V)^a·vvm^b"),
        otr_mmol_l_h=_q("OTR", otr(k, req.oxygen_saturation_mmol_l, do), "mmol/L/h", category, "OTR = kLa·(C* − C)",
                        "C from DO % via the DO concentration conversion assumption."),
        our_mmol_l_h=_q("OUR", our(req.q_o2_pmol_per_cell_h, cells), "mmol/L/h", category, "OUR = qO2·X",
                        "Cell density carried over from the source (baseline, not predicted)." if category == SCENARIO else None),
    )


def _row(strategy, parameter, unit, source, target, formula, assumption) -> StrategyRow:
    change = target - source if source is not None and target is not None else None
    return StrategyRow(strategy=strategy, label=STRATEGY_LABELS[strategy], parameter=parameter, unit=unit,
                       source=source, target=target, change=change, formula=formula, assumption=assumption,
                       category=SCENARIO if target is not None else NOT_AVAILABLE)


def model_scale_up(session: Session, row: ExperimentRow, req: ScaleUpModelRequest) -> ScaleUpModelResult:
    if row.scale_liters <= 0:
        raise ScaleUpModelError("Source experiment has a non-positive scale; cannot model scale-up.")
    v_s, v_t = row.scale_liters, req.target_scale_liters
    obs = [repo.to_observation_read(r) for r in repo.list_observations(session, row.experiment_id)]
    latest = {n: (s.final if (s := summarize_parameter(n, obs)) else None)
              for n in ("agitation_rpm", "aeration_rate", "dissolved_oxygen_percent", "cell_density")}
    rpm_s, vvm_s, do, cells = (latest[k] for k in ("agitation_rpm", "aeration_rate", "dissolved_oxygen_percent", "cell_density"))
    d_s, d_t = req.source_impeller_diameter_m, req.target_impeller_diameter_m

    observed = [
        _q("Source agitation (latest)", rpm_s, "rpm", OBSERVED), _q("Source aeration (latest)", vvm_s, "vvm", OBSERVED),
        _q("Dissolved oxygen (latest)", do, "% air sat.", OBSERVED), _q("Cell density (latest)", cells, "×10⁶ cells/mL", OBSERVED),
        _q("Source working volume", v_s, "L", OBSERVED),
    ]
    c = req.constants
    assumptions = [
        _q("Target working volume", v_t, "L", SCENARIO),
        _q("Source impeller diameter", d_s, "m", ASSUMPTION, note="User-supplied geometry."),
        _q("Target impeller diameter", d_t, "m", ASSUMPTION, note="User-supplied geometry."),
        _q("Power number Np", req.power_number, "-", ASSUMPTION, note="Default 5 (order of a Rushton turbine; pitched-blade ≈ 1.3–1.7)."),
        _q("Liquid density ρ", req.liquid_density_kg_m3, "kg/m³", ASSUMPTION, note="Default: water-like medium."),
        _q("kLa constant K", c.k, "1/h", ASSUMPTION, note="Illustrative, not a universal constant."),
        _q("kLa exponent a (P/V)", c.a, "-", ASSUMPTION), _q("kLa exponent b (vvm)", c.b, "-", ASSUMPTION),
        _q("O₂ saturation C*", req.oxygen_saturation_mmol_l, "mmol/L", ASSUMPTION,
           note="DO concentration conversion assumption: C = DO% / 100 × C* (air saturation, ~37 °C)."),
        _q("Specific O₂ uptake qO2", req.q_o2_pmol_per_cell_h, "pmol/cell/h", ASSUMPTION, note="Scenario value; varies by cell line and phase."),
    ]

    source = _conditions(req, v_s, rpm_s, OBSERVED, vvm_s, OBSERVED, d_s, do, cells, DERIVED)
    rpm_t = target_rpm(req.agitation_strategy, rpm_s, d_s, d_t, v_s, v_t)
    vvm_t, _ = target_aeration(req.aeration_strategy, vvm_s, v_s, v_t)
    target = _conditions(req, v_t, rpm_t, SCENARIO, vvm_t, SCENARIO, d_t, do, cells, SCENARIO)

    rows: list[StrategyRow] = []
    pv_s, tip_s = source.power_per_volume_w_m3.value, source.tip_speed_m_s.value
    for strat, formula, assumption in (
        ("constant_rpm", "N_t = N_s", "Same impeller speed at both scales."),
        ("constant_tip_speed", "N_t = N_s · D_s / D_t", "Same impeller tip speed; requires both impeller diameters."),
        ("constant_pv", "N_t = N_s · (D_s/D_t)^(5/3) · (V_t/V_s)^(1/3)", "Same power per volume; P/V ∝ N³·D⁵/V; requires both diameters."),
    ):
        n_t = target_rpm(strat, rpm_s, d_s, d_t, v_s, v_t)
        rows += [
            _row(strat, "Agitation", "rpm", rpm_s, n_t, formula, assumption),
            _row(strat, "Tip speed", "m/s", tip_s, tip_speed(n_t, d_t), "tip = π·D·N", assumption),
            _row(strat, "P/V", "W/m³", pv_s, power_per_volume(req.power_number, req.liquid_density_kg_m3, n_t, d_t, v_t),
                 "P/V = Np·ρ·N³·D⁵ / V", assumption),
        ]
    q_s = None if vvm_s is None else vvm_s * v_s
    for strat, assumption in (("constant_vvm", "Same gas volume per liquid volume per minute."),
                              ("constant_gas_flow", "Same total gas flow as the source vessel.")):
        vvm_x, q_x = target_aeration(strat, vvm_s, v_s, v_t)
        rows += [
            _row(strat, "Gas flow", "L/min", q_s, q_x, "Q_t = vvm·V_t" if strat == "constant_vvm" else "Q_t = Q_s", assumption),
            _row(strat, "Aeration", "vvm", vvm_s, vvm_x, "vvm_t = Q_t / V_t", assumption),
        ]

    notes = [
        "Source quantities use the latest recorded values of the source experiment; target quantities use the selected strategies.",
        "OUR at the target uses the source cell density as a baseline; it is not a growth prediction.",
        "No strategy is ranked or recommended; compare them against process knowledge and experimental data.",
    ]
    if d_s is None or d_t is None:
        notes.append("Impeller diameters were not supplied, so P/V, tip speed, kLa, OTR and geometry-based strategies are not available.")
    if not obs:
        notes.append("The source experiment has no observations, so no source process values are available.")

    return ScaleUpModelResult(
        experiment_id=row.experiment_id, source_scale_liters=v_s, target_scale_liters=v_t,
        observed=observed, assumptions=assumptions, source=source, target=target,
        oxygen_balance_source=oxygen_balance(source.otr_mmol_l_h.value, source.our_mmol_l_h.value),
        oxygen_balance_target=oxygen_balance(target.otr_mmol_l_h.value, target.our_mmol_l_h.value),
        agitation_strategy=req.agitation_strategy, aeration_strategy=req.aeration_strategy,
        strategy_comparison=rows, notes=notes,
    )
