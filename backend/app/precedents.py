"""Alert Investigation - finding precedents (Phase 18).

"Has the same rule been triggered before in our stored experiments, and what did the stored
data show afterwards?" A precedent is an EXACT rule match (same finding type, parameter and
direction; for co-occurrence the same parameter set) found by re-running the existing
`anomaly.detect()` on stored observations. No similarity, scoring, ranking or ML; no causal
inference; nothing is stored and Gemini is never called here.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlmodel import Session, select

from . import repository as repo
from .anomaly import DEFAULT_CONFIG, Finding, _meta, _series, detect
from .db_models import ExperimentRow
from .monitoring import alert_key

MAX_EXPERIMENTS = 100  # most recently created experiments searched (prototype cap)
MAX_LATER_FINDINGS = 10
MAX_PRECEDENTS_FOR_AI = 5
DEFAULT_FOLLOW_UP_HOURS = 12.0

SEARCHABLE_TYPES = ("range", "sudden_change", "trend", "co_occurrence")
DIRECTIONS = {"range": ("above", "below"), "sudden_change": ("increased", "decreased"), "trend": ("increased", "decreased")}
PARAMETERS = sorted(set(DEFAULT_CONFIG.ranges) | set(DEFAULT_CONFIG.changes))

NO_CAUSATION = "No causal inference is made from these historical observations."
LIMITATIONS = [
    "Precedents are exact matches of the same prototype monitoring rule (default configuration) in stored data; "
    "they are not assessed for similarity of the process or its conditions.",
    NO_CAUSATION,
    "What happened afterwards is what the stored observations recorded; it is not a prediction for the current run.",
    "Follow-up values are never extrapolated beyond the last stored observation.",
]


# --- request ----------------------------------------------------------------------------------

class CurrentFinding(BaseModel):
    """The finding being investigated, so it is never its own precedent (located server-side when stored)."""

    model_config = ConfigDict(extra="forbid")

    experiment_id: str = Field(min_length=1, max_length=100)
    alert_id: str = Field(min_length=1, max_length=200)


class PrecedentQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["range", "sudden_change", "trend", "co_occurrence"]
    parameter: str | None = None
    direction: Literal["above", "below", "increased", "decreased"] | None = None
    related_parameters: list[str] | None = Field(default=None, max_length=len(PARAMETERS))
    exclude_experiment_id: str | None = Field(default=None, min_length=1, max_length=100)
    current: CurrentFinding | None = None
    follow_up_hours: float = Field(default=DEFAULT_FOLLOW_UP_HOURS, gt=0, le=240, allow_inf_nan=False)

    @field_validator("parameter")
    @classmethod
    def _known_parameter(cls, value):
        if value is not None and value not in PARAMETERS:
            raise ValueError(f"unknown parameter; allowed: {', '.join(PARAMETERS)}")
        return value

    @field_validator("related_parameters")
    @classmethod
    def _known_related(cls, value):
        if value is not None:
            unknown = [p for p in value if p not in PARAMETERS]
            if unknown:
                raise ValueError(f"unknown related parameter(s): {', '.join(unknown)}")
            value = sorted(set(value))
        return value

    @model_validator(mode="after")
    def _consistent(self):
        if self.type == "co_occurrence":
            if self.parameter is not None or self.direction is not None:
                raise ValueError("co_occurrence is matched by related_parameters only (no parameter or direction)")
            if not self.related_parameters or len(self.related_parameters) < 2:
                raise ValueError("co_occurrence requires at least two related_parameters")
        else:
            if self.parameter is None or self.direction is None:
                raise ValueError(f"{self.type} requires parameter and direction")
            if self.direction not in DIRECTIONS[self.type]:
                raise ValueError(f"direction for {self.type} must be one of {', '.join(DIRECTIONS[self.type])}")
            if self.related_parameters:
                raise ValueError("related_parameters is only used for co_occurrence")
        return self


# --- response ---------------------------------------------------------------------------------

class RangeReturn(BaseModel):
    """DERIVED CALCULATION from OBSERVED DATA: position of the parameter relative to its prototype range."""

    status: Literal["inside_at_trigger", "returned", "not_observed_in_window", "no_prototype_range", "no_value"]
    returned_at_hours: float | None = None
    range_min: float | None = None
    range_max: float | None = None
    note: str


class WindowValue(BaseModel):
    """OBSERVED DATA: last stored value of a parameter within the follow-up window."""

    parameter: str
    label: str
    unit: str | None
    value: float | None
    culture_time_hours: float | None


class LaterFinding(BaseModel):
    type_label: str
    parameter_label: str | None
    severity: str
    culture_time_hours: float | None
    message: str


class FollowUp(BaseModel):
    window_start_hours: float
    window_end_hours: float
    observed_until_hours: float | None  # last stored observation inside the window
    run_ended_before_window_end: bool
    range_return: RangeReturn | None  # None for co-occurrence (several parameters)
    values_at_window_end: list[WindowValue]
    later_findings: list[LaterFinding]
    later_findings_omitted: int = 0


class Precedent(BaseModel):
    experiment_id: str
    name: str
    data_source: str
    scale_liters: float
    same_run: bool  # an earlier episode in the run being investigated
    relation: str  # "Earlier in this run" | "Stored experiment"
    finding_type: str
    type_label: str
    parameter: str | None
    parameter_label: str | None
    related_parameters: list[str]
    direction: str | None
    trigger_time_hours: float  # culture time the rule was first met (episode start for range/trend)
    episode_end_hours: float | None
    severity: str
    message: str
    follow_up: FollowUp


class PrecedentResult(BaseModel):
    criteria: dict
    precedents: list[Precedent]
    matching_experiments: int
    experiments_searched: int
    experiments_skipped: int  # beyond the cap of most recently created experiments
    experiments_excluded: int
    search_cap: int = MAX_EXPERIMENTS
    no_causation_note: str = NO_CAUSATION
    limitations: list[str]


# --- calculation ------------------------------------------------------------------------------

def trigger_time(finding: Finding) -> float:
    """When the rule was first met: episode start for range/trend, interval end for changes."""
    if finding.type in ("range", "trend") and finding.previous_time_hours is not None:
        return finding.previous_time_hours
    return finding.culture_time_hours


def matches(finding: Finding, query: PrecedentQuery) -> bool:
    if finding.type != query.type:
        return False
    if query.type == "co_occurrence":
        return sorted(set(finding.related_parameters)) == query.related_parameters
    return finding.parameter == query.parameter and finding.direction == query.direction


def query_for(finding: Finding) -> dict | None:
    """Search criteria describing a finding (None for finding types that are not searchable)."""
    if finding.type not in SEARCHABLE_TYPES:
        return None
    if finding.type == "co_occurrence":
        return {"type": "co_occurrence", "related_parameters": sorted(set(finding.related_parameters))}
    return {"type": finding.type, "parameter": finding.parameter, "direction": finding.direction}


def _range_return(name: str, series: list[tuple[float, float]], start: float, end: float) -> RangeReturn:
    rule = DEFAULT_CONFIG.ranges.get(name)
    if rule is None:
        return RangeReturn(status="no_prototype_range", note="This parameter has no prototype monitoring range.")
    bounds = {"range_min": rule.min, "range_max": rule.max}
    window = [(t, v) for t, v in series if start <= t <= end]
    if not window:
        return RangeReturn(status="no_value", note="No stored value in the follow-up window.", **bounds)
    inside = lambda v: rule.min <= v <= rule.max  # noqa: E731
    at_trigger = [v for t, v in window if t == start]
    if at_trigger and inside(at_trigger[-1]):
        return RangeReturn(status="inside_at_trigger", note="Inside the prototype range at the trigger time.", **bounds)
    later = next((t for t, v in window if t > start and inside(v)), None)
    if later is not None:
        return RangeReturn(status="returned", returned_at_hours=later,
                           note=f"The stored data returned inside the prototype range at {later:g} h.", **bounds)
    return RangeReturn(status="not_observed_in_window",
                       note="A return inside the prototype range was not observed in the stored data within the window.", **bounds)


def _follow_up(finding: Finding, all_findings: list[Finding], observations, hours: float) -> FollowUp:
    start = trigger_time(finding)
    end = start + hours
    names = [finding.parameter] if finding.parameter else sorted(set(finding.related_parameters))
    in_window = [o.culture_time_hours for o in observations if start <= o.culture_time_hours <= end]
    last_time = max(o.culture_time_hours for o in observations)
    values = []
    for name in names:
        series = [(t, v) for t, v in _series(observations, name) if start <= t <= end]
        label, unit, _ = _meta(name)
        t_last, v_last = series[-1] if series else (None, None)
        values.append(WindowValue(parameter=name, label=label, unit=unit, value=v_last, culture_time_hours=t_last))
    own_key = alert_key(finding)
    later = [f for f in all_findings
             if alert_key(f) != own_key and f.culture_time_hours is not None and start < f.culture_time_hours <= end]
    later.sort(key=lambda f: (f.culture_time_hours, f.type, f.parameter or ""))
    return FollowUp(
        window_start_hours=start, window_end_hours=end,
        observed_until_hours=max(in_window) if in_window else None,
        run_ended_before_window_end=last_time < end,
        range_return=_range_return(finding.parameter, _series(observations, finding.parameter), start, end) if finding.parameter else None,
        values_at_window_end=values,
        later_findings=[LaterFinding(type_label=f.type_label, parameter_label=f.parameter_label, severity=f.severity,
                                     culture_time_hours=f.culture_time_hours, message=f.message) for f in later[:MAX_LATER_FINDINGS]],
        later_findings_omitted=max(0, len(later) - MAX_LATER_FINDINGS),
    )


def find_precedents(session: Session, query: PrecedentQuery) -> PrecedentResult:
    total = len(session.exec(select(ExperimentRow.id)).all())
    rows = session.exec(
        select(ExperimentRow).order_by(ExperimentRow.created_at.desc(), ExperimentRow.experiment_id).limit(MAX_EXPERIMENTS)
    ).all()
    precedents, excluded, searched = [], 0, 0
    for row in rows:
        if row.experiment_id == query.exclude_experiment_id:
            excluded += 1
            continue
        searched += 1
        observations = [repo.to_observation_read(r) for r in repo.list_observations(session, row.experiment_id)]
        if not observations:
            continue
        findings = detect(row.experiment_id, observations)
        same_run = query.current is not None and query.current.experiment_id == row.experiment_id
        cutoff = None
        if same_run:
            current = next((f for f in findings if alert_key(f) == query.current.alert_id), None)
            cutoff = trigger_time(current) if current is not None else None
        for f in findings:
            if not matches(f, query):
                continue
            if same_run and (alert_key(f) == query.current.alert_id or (cutoff is not None and trigger_time(f) >= cutoff)):
                continue  # never the finding itself, and only EARLIER episodes of the same run
            precedents.append(Precedent(
                experiment_id=row.experiment_id, name=row.name, data_source=row.data_source, scale_liters=row.scale_liters,
                same_run=same_run, relation="Earlier in this run" if same_run else "Stored experiment",
                finding_type=f.type, type_label=f.type_label, parameter=f.parameter, parameter_label=f.parameter_label,
                related_parameters=sorted(set(f.related_parameters)), direction=f.direction,
                trigger_time_hours=trigger_time(f), episode_end_hours=f.culture_time_hours, severity=f.severity,
                message=f.message, follow_up=_follow_up(f, findings, observations, query.follow_up_hours),
            ))
    # Deterministic order (not a ranking): same run first, then experiment creation order (newest first), then time.
    order = {row.experiment_id: i for i, row in enumerate(rows)}
    precedents.sort(key=lambda p: (not p.same_run, order[p.experiment_id], p.trigger_time_hours))
    limitations = list(LIMITATIONS)
    skipped = max(0, total - len(rows))
    if skipped:
        limitations.append(f"Only the {MAX_EXPERIMENTS} most recently created experiments were searched; {skipped} older experiment(s) were not.")
    return PrecedentResult(
        criteria=query.model_dump(exclude_none=True),
        precedents=precedents,
        matching_experiments=len({p.experiment_id for p in precedents}),
        experiments_searched=searched,
        experiments_skipped=skipped,
        experiments_excluded=excluded,
        search_cap=MAX_EXPERIMENTS,
        limitations=limitations,
    )


def precedent_summary(result: PrecedentResult) -> dict:
    """Compact, bounded summary for the Copilot: at most 5 precedents, no evidence points, no observations."""
    def compact(p: Precedent) -> dict:
        fu = p.follow_up
        return {
            "experiment_id": p.experiment_id, "name": p.name, "scale_liters": p.scale_liters, "relation": p.relation,
            "message": p.message, "severity": p.severity, "trigger_time_hours": p.trigger_time_hours,
            "follow_up_window_hours": [fu.window_start_hours, fu.window_end_hours],
            "run_ended_before_window_end": fu.run_ended_before_window_end,
            "range_return": fu.range_return.note if fu.range_return else None,
            "values_at_window_end": [f"{v.label}: {v.value} {v.unit or ''} at {v.culture_time_hours} h".strip()
                                     if v.value is not None else f"{v.label}: no stored value" for v in fu.values_at_window_end],
            "later_findings": [f"{f.type_label}{' – ' + f.parameter_label if f.parameter_label else ''} ({f.severity}, {f.culture_time_hours} h)"
                               for f in fu.later_findings],
        }

    return {
        "note": "Same-rule matches in stored data: what was recorded, not a cause, a prediction or a recommendation.",
        "criteria": result.criteria,
        "precedents_total": len(result.precedents),
        "precedents": [compact(p) for p in result.precedents[:MAX_PRECEDENTS_FOR_AI]],
        "precedents_omitted": max(0, len(result.precedents) - MAX_PRECEDENTS_FOR_AI),
        "experiments_searched": result.experiments_searched,
        "experiments_skipped": result.experiments_skipped,
        "limitations": result.limitations,
    }
