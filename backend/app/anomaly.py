"""Deterministic, explainable process-condition checks on stored observations.

Every finding is produced by a documented rule and carries its evidence (values,
times, thresholds). The ranges and thresholds are PROTOTYPE MONITORING DEFAULTS,
configurable via MonitoringConfig; they are not universal biological limits.
No AI, no machine learning, no risk score, no causal claims. Nothing is stored.

Checks:
- range:          value outside the prototype monitoring range (consecutive
                  out-of-range readings of one parameter are grouped into one finding)
- sudden_change:  change between consecutive readings above the threshold
- trend:          >= trend_min_points consecutive strictly increasing/decreasing readings
                  whose total change is >= trend_change_fraction × the change threshold
- data_coverage:  < 2 time points, missing optional parameters, repeated time points,
                  gaps > large_gap_factor × the median interval
- co_occurrence:  two or more sudden changes over the same observation interval
"""

from statistics import median
from typing import Literal

from pydantic import BaseModel, Field
from sqlmodel import Session

from . import repository as repo
from .analysis import PARAMETER_DECIMALS, _sentence, assess_data_quality
from .db_models import ExperimentRow
from .models import ExperimentRead, Observation

Severity = Literal["info", "attention", "significant"]
SEVERITY_ORDER = {"significant": 0, "attention": 1, "info": 2}

TYPE_LABELS = {
    "range": "Parameter outside configured range",
    "sudden_change": "Rapid parameter change",
    "trend": "Persistent trend",
    "co_occurrence": "Co-occurring changes",
    "data_coverage": "Data coverage",
}


class RangeRule(BaseModel):
    min: float
    max: float
    severe_margin: float = Field(description="Beyond the range by more than this -> significant.")


class ChangeRule(BaseModel):
    kind: Literal["absolute", "relative"]
    threshold: float = Field(gt=0, description="Absolute units, or a fraction of the previous value (0.3 = 30%).")


class MonitoringConfig(BaseModel):
    note: str = "Prototype monitoring defaults, configurable; not universal biological limits for every cell line."
    ranges: dict[str, RangeRule] = {
        "temperature_c": RangeRule(min=34, max=39, severe_margin=1.0),
        "ph": RangeRule(min=6.5, max=7.5, severe_margin=0.3),
        "dissolved_oxygen_percent": RangeRule(min=20, max=100, severe_margin=10),
        "agitation_rpm": RangeRule(min=0, max=500, severe_margin=100),
        "cell_density": RangeRule(min=0, max=20, severe_margin=5),
    }
    changes: dict[str, ChangeRule] = {
        "temperature_c": ChangeRule(kind="absolute", threshold=1.0),
        "ph": ChangeRule(kind="absolute", threshold=0.3),
        "dissolved_oxygen_percent": ChangeRule(kind="absolute", threshold=15),
        "agitation_rpm": ChangeRule(kind="absolute", threshold=50),
        "cell_density": ChangeRule(kind="relative", threshold=0.30),
        "feed_rate": ChangeRule(kind="relative", threshold=0.30),
        "aeration_rate": ChangeRule(kind="relative", threshold=0.30),
        "nutrient_concentration": ChangeRule(kind="relative", threshold=0.30),
    }
    significant_change_multiplier: float = Field(default=2.0, description="Change > multiplier × threshold -> significant.")
    trend_min_points: int = Field(default=3, ge=3)
    trend_change_fraction: float = Field(default=0.5, description="Trend net change must be >= this × the change threshold.")
    large_gap_factor: float = Field(default=3.0, description="Gap > factor × median interval -> data-coverage note.")


DEFAULT_CONFIG = MonitoringConfig()


class EvidencePoint(BaseModel):
    culture_time_hours: float
    value: float


class Finding(BaseModel):
    finding_id: str
    experiment_id: str
    type: Literal["range", "sudden_change", "trend", "co_occurrence", "data_coverage"]
    type_label: str
    severity: Severity
    parameter: str | None = None
    parameter_label: str | None = None
    unit: str | None = None
    message: str
    culture_time_hours: float | None = None  # time of the (current / last) observation involved
    previous_time_hours: float | None = None  # time of the previous / first observation involved
    observed_value: float | None = None
    previous_value: float | None = None
    threshold: float | None = None
    threshold_kind: Literal["absolute", "relative"] | None = None
    expected_min: float | None = None
    expected_max: float | None = None
    absolute_change: float | None = None
    relative_change_percent: float | None = None
    direction: Literal["increased", "decreased", "above", "below"] | None = None
    evidence: list[str] = []
    points: list[EvidencePoint] = []
    related_parameters: list[str] = []
    related_finding_ids: list[str] = []


class SeverityCounts(BaseModel):
    info: int = 0
    attention: int = 0
    significant: int = 0


class AnomalyReport(BaseModel):
    experiment: ExperimentRead
    experiment_id: str
    observation_count: int
    finding_count: int
    counts: SeverityCounts
    findings: list[Finding]  # most severe first, then by culture time
    summary: list[str]
    configuration: MonitoringConfig


# --- helpers -------------------------------------------------------------------------

def _meta(name: str) -> tuple[str, str | None, int]:
    field = Observation.model_fields[name]
    return field.title or name, (field.json_schema_extra or {}).get("unit"), PARAMETER_DECIMALS.get(name, 2)


def _v(value: float, decimals: int, unit: str | None = None) -> str:
    text = f"{value:.{decimals}f}"
    return f"{text} {unit}" if unit else text


def _h(hours: float) -> str:
    return f"{hours:g} h"


def _series(observations: list[Observation], name: str) -> list[tuple[float, float]]:
    """(culture time, value) for observations that have this parameter, in chronological order."""
    return [(o.culture_time_hours, getattr(o, name)) for o in observations if getattr(o, name) is not None]


def _monotonic_runs(series: list[tuple[float, float]]) -> list[list[tuple[float, float]]]:
    """Maximal runs of consecutive readings that are strictly increasing or strictly decreasing."""
    runs, i = [], 0
    while i < len(series) - 1:
        step = series[i + 1][1] - series[i][1]
        if step == 0:
            i += 1
            continue
        j = i + 1
        while j + 1 < len(series):
            nxt = series[j + 1][1] - series[j][1]
            if nxt == 0 or (nxt > 0) != (step > 0):
                break
            j += 1
        runs.append(series[i:j + 1])
        i = j  # the next run starts at the turning point
    return runs


def _rule_text(rule: ChangeRule, decimals: int, unit: str | None) -> str:
    return f"{rule.threshold * 100:g}%" if rule.kind == "relative" else _v(rule.threshold, decimals, unit)


# --- checks --------------------------------------------------------------------------

def check_ranges(experiment_id: str, observations: list[Observation], config: MonitoringConfig) -> list[Finding]:
    findings = []
    for name, rule in config.ranges.items():
        label, unit, d = _meta(name)
        episode: list[tuple[float, float]] = []
        side = None

        def close():
            if not episode:
                return
            extreme = min(v for _, v in episode) if side == "below" else max(v for _, v in episode)
            bound = rule.min if side == "below" else rule.max
            beyond = bound - extreme if side == "below" else extreme - bound
            (t0, _), (t1, _) = episode[0], episode[-1]
            where = (
                f"at {_h(t0)}: {_v(extreme, d, unit)}" if len(episode) == 1
                else f"in {len(episode)} consecutive observations from {_h(t0)} to {_h(t1)} "
                     f"({'lowest' if side == 'below' else 'highest'} {_v(extreme, d, unit)})"
            )
            findings.append(Finding(
                finding_id=f"range-{name}-{len(findings) + 1}",
                experiment_id=experiment_id, type="range", type_label=TYPE_LABELS["range"],
                severity="significant" if beyond > rule.severe_margin else "attention",
                parameter=name, parameter_label=label, unit=unit,
                message=_sentence(f"{label} was {side} the prototype monitoring range "
                                  f"({_v(rule.min, d)}–{_v(rule.max, d, unit)}) {where}"),
                culture_time_hours=t1, previous_time_hours=t0,
                observed_value=extreme, expected_min=rule.min, expected_max=rule.max, direction=side,
                evidence=[
                    f"Prototype monitoring range: {_v(rule.min, d)}–{_v(rule.max, d, unit)}.",
                    f"{len(episode)} observation(s) {side} the range; furthest value {_v(extreme, d, unit)} "
                    f"({_v(beyond, d, unit)} {side} the {'lower' if side == 'below' else 'upper'} limit).",
                    f"Significant if more than {_v(rule.severe_margin, d, unit)} beyond the range.",
                ],
                points=[EvidencePoint(culture_time_hours=t, value=v) for t, v in episode],
            ))
            episode.clear()

        for t, v in _series(observations, name):
            current = "below" if v < rule.min else "above" if v > rule.max else None
            if current != side:
                close()
                side = current
            if current:
                episode.append((t, v))
        close()
    return findings


def check_sudden_changes(experiment_id: str, observations: list[Observation], config: MonitoringConfig) -> list[Finding]:
    findings = []
    for name, rule in config.changes.items():
        label, unit, d = _meta(name)
        series = _series(observations, name)
        for (t0, v0), (t1, v1) in zip(series, series[1:]):
            change = v1 - v0
            relative = change / v0 if v0 != 0 else None
            if rule.kind == "absolute":
                size = abs(change)
            elif relative is None:
                continue  # relative change undefined when the previous value is 0
            else:
                size = abs(relative)
            if size <= rule.threshold:
                continue
            direction = "increased" if change > 0 else "decreased"
            rel_text = f"{relative * 100:+.1f}%" if relative is not None else "n/a (previous value is 0)"
            findings.append(Finding(
                finding_id=f"change-{name}-{len(findings) + 1}",
                experiment_id=experiment_id, type="sudden_change", type_label=TYPE_LABELS["sudden_change"],
                severity="significant" if size > rule.threshold * config.significant_change_multiplier else "attention",
                parameter=name, parameter_label=label, unit=unit,
                message=_sentence(f"{label} {direction} from {_v(v0, d)} to {_v(v1, d, unit)} "
                                  f"between {_h(t0)} and {_h(t1)}"),
                culture_time_hours=t1, previous_time_hours=t0,
                observed_value=v1, previous_value=v0,
                threshold=rule.threshold, threshold_kind=rule.kind,
                absolute_change=change,
                relative_change_percent=relative * 100 if relative is not None else None,
                direction=direction,
                evidence=[
                    f"Change between consecutive observations: {change:+.{d}f}{' ' + unit if unit else ''} ({rel_text}).",
                    f"Prototype monitoring threshold: {'more than ' + _rule_text(rule, d, unit)}"
                    f" {'relative' if rule.kind == 'relative' else 'absolute'} change.",
                    f"Significant if more than {config.significant_change_multiplier:g}× the threshold.",
                    f"Interval: {_h(t0)} to {_h(t1)} ({_h(t1 - t0)}).",
                ],
                points=[EvidencePoint(culture_time_hours=t0, value=v0), EvidencePoint(culture_time_hours=t1, value=v1)],
            ))
    return findings


def check_trends(experiment_id: str, observations: list[Observation], config: MonitoringConfig) -> list[Finding]:
    findings = []
    for name, rule in config.changes.items():
        label, unit, d = _meta(name)
        min_change = rule.threshold * config.trend_change_fraction
        for run in _monotonic_runs(_series(observations, name)):
            if len(run) < config.trend_min_points:
                continue
            (t0, v0), (t1, v1) = run[0], run[-1]
            net = v1 - v0
            size = abs(net) if rule.kind == "absolute" else (abs(net / v0) if v0 != 0 else None)
            if size is None or size < min_change:
                continue
            direction = "increased" if net > 0 else "decreased"
            findings.append(Finding(
                finding_id=f"trend-{name}-{len(findings) + 1}",
                experiment_id=experiment_id, type="trend", type_label=TYPE_LABELS["trend"],
                severity="info",
                parameter=name, parameter_label=label, unit=unit,
                message=_sentence(f"{label} {direction} across {len(run)} consecutive observations from "
                                  f"{_h(t0)} to {_h(t1)} ({_v(v0, d)} → {_v(v1, d, unit)})"),
                culture_time_hours=t1, previous_time_hours=t0,
                observed_value=v1, previous_value=v0,
                threshold=min_change, threshold_kind=rule.kind,
                absolute_change=net,
                relative_change_percent=net / v0 * 100 if v0 != 0 else None,
                direction=direction,
                evidence=[
                    f"{len(run)} consecutive observations, each {'higher' if net > 0 else 'lower'} than the previous.",
                    f"Total change {net:+.{d}f}{' ' + unit if unit else ''} "
                    f"(minimum for a trend: {_rule_text(rule.model_copy(update={'threshold': min_change}), d, unit)}"
                    f" and at least {config.trend_min_points} observations).",
                    "A trend is a description of the data, not an assessment of its cause or impact.",
                ],
                points=[EvidencePoint(culture_time_hours=t, value=v) for t, v in run],
            ))
    return findings


def check_co_occurrence(experiment_id: str, changes: list[Finding], config: MonitoringConfig) -> list[Finding]:
    by_interval: dict[tuple[float, float], list[Finding]] = {}
    for f in changes:
        by_interval.setdefault((f.previous_time_hours, f.culture_time_hours), []).append(f)
    findings = []
    for (t0, t1), group in sorted(by_interval.items()):
        if len(group) < 2:
            continue
        mid = lambda label: label if label == "pH" else label[0].lower() + label[1:]  # noqa: E731
        parts = [f"{f.parameter_label if i == 0 else mid(f.parameter_label)} {f.direction}" for i, f in enumerate(group)]
        text = " while ".join(parts) if len(parts) == 2 else ", ".join(parts[:-1]) + " and " + parts[-1]
        significant = sum(f.severity == "significant" for f in group)
        findings.append(Finding(
            finding_id=f"cooccurrence-{len(findings) + 1}",
            experiment_id=experiment_id, type="co_occurrence", type_label=TYPE_LABELS["co_occurrence"],
            severity="significant" if significant >= 2 else "attention",
            message=f"{text} over the same observation interval ({_h(t0)} to {_h(t1)}).",
            culture_time_hours=t1, previous_time_hours=t0,
            evidence=[f.message for f in group] + [
                "Reported because these rapid changes share an interval; no causal relationship is inferred.",
                "Significant when two or more of the changes are individually significant.",
            ],
            related_parameters=[f.parameter for f in group],
            related_finding_ids=[f.finding_id for f in group],
        ))
    return findings


def check_data_coverage(experiment_id: str, observations: list[Observation], config: MonitoringConfig) -> list[Finding]:
    if not observations:
        return []
    quality = assess_data_quality(observations)
    findings = []

    def add(message: str, evidence: list[str], parameter: str | None = None, **extra):
        label = _meta(parameter)[0] if parameter else None
        findings.append(Finding(
            finding_id=f"coverage-{len(findings) + 1}", experiment_id=experiment_id,
            type="data_coverage", type_label=TYPE_LABELS["data_coverage"], severity="info",
            parameter=parameter, parameter_label=label, message=message, evidence=evidence, **extra,
        ))

    times = [o.culture_time_hours for o in observations]
    if quality.distinct_time_points < 2:
        add("Only one distinct culture-time point is available; change and trend checks are limited.",
            [f"{quality.observation_count} observation(s) at {_h(times[0])}."], culture_time_hours=times[0])

    never = [m.label for m in quality.missing_values if m.missing == quality.observation_count]
    if never:
        add(f"Optional parameter(s) not recorded: {', '.join(never)}.",
            ["These parameters are not checked. Missing optional data is not treated as an anomaly."])
    for m in quality.missing_values:
        if 0 < m.missing < quality.observation_count:
            add(f"{m.label} is missing in {m.missing} of {quality.observation_count} observations.",
                ["Checks for this parameter use only the observations that have a value."], parameter=m.parameter)

    if quality.duplicate_time_points:
        repeated = sorted({t for t in times if times.count(t) > 1})
        add(f"{quality.duplicate_time_points} observation(s) share a culture time with another observation "
            f"({', '.join(_h(t) for t in repeated)}).",
            ["Observations with the same culture time are compared in the order they were recorded."])

    distinct = sorted(set(times))
    intervals = [b - a for a, b in zip(distinct, distinct[1:])]
    if len(intervals) >= 2:
        typical = median(intervals)
        for a, b in zip(distinct, distinct[1:]):
            if typical > 0 and b - a > config.large_gap_factor * typical:
                add(f"Observations contain a {_h(b - a)} gap between {_h(a)} and {_h(b)}.",
                    [f"Median interval between time points: {_h(typical)}.",
                     f"Gaps longer than {config.large_gap_factor:g}× the median interval are reported.",
                     "Changes across a gap compare readings that are far apart in time."],
                    culture_time_hours=b, previous_time_hours=a, absolute_change=b - a)
    return findings


# --- entry points --------------------------------------------------------------------

def detect(experiment_id: str, observations: list[Observation], config: MonitoringConfig = DEFAULT_CONFIG) -> list[Finding]:
    """All findings for chronologically ordered observations, most severe first."""
    changes = check_sudden_changes(experiment_id, observations, config)
    findings = (
        check_ranges(experiment_id, observations, config)
        + changes
        + check_co_occurrence(experiment_id, changes, config)
        + check_trends(experiment_id, observations, config)
        + check_data_coverage(experiment_id, observations, config)
    )
    return sorted(findings, key=lambda f: (SEVERITY_ORDER[f.severity], f.culture_time_hours if f.culture_time_hours is not None else -1))


def summarize(findings: list[Finding], observations: list[Observation]) -> list[str]:
    n, m = len(findings), len(observations)
    if not observations:
        return ["No observations have been recorded, so no checks were run."]
    lines = [f"{n} finding(s) were detected across {m} observation(s)." if n else
             f"No findings were detected across {m} observation(s) with the prototype monitoring configuration."]
    by_type: dict[str, int] = {}
    by_param: dict[str, int] = {}
    for f in findings:
        by_type[f.type_label] = by_type.get(f.type_label, 0) + 1
        for p in [f.parameter] if f.parameter else f.related_parameters:
            label = _meta(p)[0]
            by_param[label] = by_param.get(label, 0) + 1
    if by_type:
        lines.append("By type: " + ", ".join(f"{label} ({count})" for label, count in by_type.items()) + ".")
    if by_param:
        lines.append("Parameters involved: " + ", ".join(f"{label} ({count})" for label, count in by_param.items()) + ".")
    out_of_range = sum(len(f.points) for f in findings if f.type == "range")
    if out_of_range:
        lines.append(f"{out_of_range} parameter reading(s) were outside a prototype monitoring range.")
    return lines


def analyze_anomalies(session: Session, row: ExperimentRow, config: MonitoringConfig = DEFAULT_CONFIG) -> AnomalyReport:
    observations = [repo.to_observation_read(r) for r in repo.list_observations(session, row.experiment_id)]
    findings = detect(row.experiment_id, observations, config)
    counts = SeverityCounts()
    for f in findings:
        setattr(counts, f.severity, getattr(counts, f.severity) + 1)
    return AnomalyReport(
        experiment=repo.to_experiment_read(row, len(observations)),
        experiment_id=row.experiment_id,
        observation_count=len(observations),
        finding_count=len(findings),
        counts=counts,
        findings=findings,
        summary=summarize(findings, observations),
        configuration=config,
    )
