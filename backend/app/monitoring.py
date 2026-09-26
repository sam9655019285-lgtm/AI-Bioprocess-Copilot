"""Live monitoring (Phase 17): turns the existing anomaly findings into live alert events.

Detection is NOT reimplemented here: every step re-runs `anomaly.detect()` on a bounded
window of the run's observations and compares the result with the previous step, keyed by
a stable alert key (anomaly finding_ids are index-based, and range/trend findings are
episodes that grow while they last). Pure logic: no database, no Gemini, no WebSocket.
"""

from collections import deque

from .anomaly import DEFAULT_CONFIG, Finding, MonitoringConfig, detect
from .models import Observation

WINDOW_SIZE = 1000  # observations kept per run (~500 h at the simulator's default 0.5 h/step)


def _t(hours: float | None) -> str:
    return "-" if hours is None else repr(round(hours, 4))


def alert_key(finding: Finding) -> str | None:
    """Stable identity of a finding across re-detections; None when it has no stable identity.

    Episodes (range, trend, data-coverage gap) keep their start time as they grow; a sudden
    change and a co-occurrence are fixed to the interval end time. Data-coverage notes without
    a culture time (e.g. "parameter never recorded") are data-quality notes, not live events.
    """
    if finding.type in ("range", "trend"):
        return f"{finding.type}:{finding.parameter}:{_t(finding.previous_time_hours)}"
    if finding.type == "sudden_change":
        return f"change:{finding.parameter}:{_t(finding.culture_time_hours)}"
    if finding.type == "co_occurrence":
        return f"cooccurrence:{_t(finding.culture_time_hours)}"
    if finding.type == "data_coverage" and finding.previous_time_hours is not None:
        return f"data_coverage:{finding.parameter or '-'}:{_t(finding.previous_time_hours)}"
    return None


def keyed_findings(findings: list[Finding]) -> dict[str, Finding]:
    """Findings that have a stable key, by key (detect() output order is preserved)."""
    out = {}
    for f in findings:
        key = alert_key(f)
        if key is not None and key not in out:
            out[key] = f
    return out


def _content(finding: Finding) -> dict:
    return finding.model_dump(exclude={"finding_id", "related_finding_ids"})


class LiveMonitor:
    """Per-run monitor. `add()` returns the alert events caused by one new observation."""

    def __init__(self, experiment_id: str, config: MonitoringConfig = DEFAULT_CONFIG, window_size: int = WINDOW_SIZE):
        self.experiment_id = experiment_id
        self.config = config
        self.window: deque[Observation] = deque(maxlen=window_size)
        self.current: dict[str, Finding] = {}
        self.first_detected: dict[str, float] = {}  # alert key -> culture time of first detection

    def add(self, observation: Observation, saved: bool = False) -> list[dict]:
        self.window.append(observation)
        now = keyed_findings(detect(self.experiment_id, list(self.window), self.config))
        events = []
        for key, finding in now.items():
            previous = self.current.get(key)
            if previous is not None and _content(previous) == _content(finding):
                continue
            event = "new" if key not in self.first_detected else "updated"
            self.first_detected.setdefault(key, observation.culture_time_hours)
            events.append({
                "type": "alert",
                "event": event,
                "alert": {
                    "alert_id": key,
                    "experiment_id": self.experiment_id,
                    "saved": saved,
                    "detected_at_hours": self.first_detected[key],
                    "finding": finding.model_dump(mode="json"),
                },
            })
        self.current = now
        return events
