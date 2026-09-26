"""PDF experiment report (Phase 11): a presentation/export of existing results.

Nothing is calculated here that another module already calculates: the report reuses the
Phase 5 analysis, Phase 7 findings and (optionally) a Phase 6 scale-up scenario recomputed
on the server. AI Analysis and Copilot content is included only when the client supplies a
result it received earlier in the session; it is validated and labelled as AI-generated.
Reports are generated on demand and never stored. Gemini is not called.
"""

import html
from datetime import datetime, timezone
from io import BytesIO

from pydantic import BaseModel, ConfigDict, Field, model_validator
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlmodel import Session

from .analysis import PARAMETER_DECIMALS, ExperimentAnalysis, analyze_experiment
from .anomaly import AnomalyReport, analyze_anomalies
from .copilot import CopilotAnswer
from .db_models import ExperimentRow
from .gemini_service import AIAnalysis
from .models import DataSource, Observation
from .scaleup import ScaleUpRequest, ScaleUpResult, simulate_scale_up

PROJECT_NAME = "AI Copilot for Scalable Cell-Culture Bioprocess Design"
REPORT_TITLE = "Cell-Culture Bioprocess Experiment Report"
NOT_AVAILABLE = "Not available"
TREND_PARAMETERS = [  # (parameter, minimum y-span so noise on a stable signal is not exaggerated)
    ("temperature_c", 1.0), ("ph", 0.2), ("dissolved_oxygen_percent", 10.0), ("agitation_rpm", 20.0), ("cell_density", 1.0),
]
MAX_CHART_POINTS = 400
MAX_FINDINGS = 100
LIMITATIONS = [
    "This application is a software decision-support prototype.",
    "Simulated bioreactor data is illustrative and not calibrated to a specific physical bioreactor or cell line.",
    "Scale-up calculations are scenario calculations and do not guarantee or predict real biological performance.",
    "AI outputs are interpretations of data supplied by the application; they are not experimental facts and may be incomplete or wrong.",
    "Anomaly findings use configurable prototype monitoring ranges and thresholds, not universal biological limits.",
    "The application does not autonomously control physical bioreactors.",
    "Final experimental decisions remain with qualified scientists and engineers.",
]


# --- Request (optional sections) ---------------------------------------------------------

class ReportAIAnalysis(BaseModel):
    """An AI Process Analysis result received earlier in the session (Phase 8 response shape)."""

    model_config = ConfigDict(extra="ignore")
    experiment_id: str | None = None
    model: str | None = None
    generated_at: datetime | None = None
    analysis: AIAnalysis


class ReportCopilot(CopilotAnswer):
    """The latest AI Copilot response received earlier in the session (Phase 9 response shape)."""

    model_config = ConfigDict(extra="ignore")
    experiment_id: str | None = None
    model: str | None = None
    generated_at: datetime | None = None
    question: str = Field(min_length=1, max_length=2000)


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scale_up: ScaleUpRequest | None = None
    ai_analysis: ReportAIAnalysis | None = None
    copilot: ReportCopilot | None = None

    def check_experiment(self, experiment_id: str) -> None:
        for name, section in (("scale_up", self.scale_up), ("ai_analysis", self.ai_analysis), ("copilot", self.copilot)):
            other = getattr(section, "source_experiment_id", None) or getattr(section, "experiment_id", None)
            if section is not None and other not in (None, experiment_id):
                raise ValueError(f"{name} belongs to experiment '{other}', not '{experiment_id}'.")


class ReportData(BaseModel):
    generated_at: datetime
    analysis: ExperimentAnalysis
    anomalies: AnomalyReport
    scale_up: ScaleUpResult | None
    ai_analysis: ReportAIAnalysis | None
    copilot: ReportCopilot | None


def build_report_data(session: Session, row: ExperimentRow, request: ReportRequest) -> ReportData:
    """Collect report content from the existing deterministic layers (no new calculations)."""
    request.check_experiment(row.experiment_id)
    return ReportData(
        generated_at=datetime.now(timezone.utc),
        analysis=analyze_experiment(session, row),
        anomalies=analyze_anomalies(session, row),
        scale_up=simulate_scale_up(session, row, request.scale_up) if request.scale_up else None,
        ai_analysis=request.ai_analysis,
        copilot=request.copilot,
    )


# --- Text helpers ------------------------------------------------------------------------

_MARKUP = {"⁶": "<super>6</super>", "₂": "<sub>2</sub>", "→": "-&gt;", "−": "-", "≥": "&gt;=", "≤": "&lt;="}
_PLAIN = {"⁶": "^6", "₂": "2", "→": "->", "−": "-", "≥": ">=", "≤": "<="}


def _cp1252(text: str) -> str:
    # The built-in PDF fonts cover Windows-1252; anything else becomes "?" rather than a broken glyph.
    return text.encode("cp1252", errors="replace").decode("cp1252")


def rich(text: object) -> str:
    """Escape for reportlab Paragraph markup and map symbols the built-in fonts lack."""
    out = html.escape(str(text), quote=False)
    for char, repl in _MARKUP.items():
        out = out.replace(char, repl)
    return _cp1252(out)


def plain(text: object) -> str:
    out = str(text)
    for char, repl in _PLAIN.items():
        out = out.replace(char, repl)
    return _cp1252(out)


def fmt(value: float | None, decimals: int = 2) -> str:
    return NOT_AVAILABLE if value is None else f"{value:,.{decimals}f}"


def hours(value: float | None) -> str:
    return NOT_AVAILABLE if value is None else f"{value:g} h"


def _meta(name: str) -> tuple[str, str | None]:
    field = Observation.model_fields[name]
    return field.title or name, (field.json_schema_extra or {}).get("unit")


# --- Table content (pure functions, tested directly) --------------------------------------

def parameter_rows(analysis: ExperimentAnalysis) -> list[list[str]]:
    """Statistics rows for every parameter; missing parameters are 'Not available', never 0."""
    by_name = {p.parameter: p for p in analysis.parameters}
    rows = []
    for name, decimals in PARAMETER_DECIMALS.items():
        label, unit = _meta(name)
        p = by_name.get(name)
        if p is None:
            rows.append([label, unit or "", "0", *[NOT_AVAILABLE] * 6])
        else:
            rows.append([label, unit or "", str(p.count), fmt(p.start, decimals), fmt(p.final, decimals),
                         fmt(p.minimum, decimals), fmt(p.maximum, decimals), fmt(p.average, decimals + 1),
                         fmt(p.delta, decimals)])
    return rows


def finding_rows(anomalies: AnomalyReport) -> list[list[str]]:
    rows = []
    for f in anomalies.findings[:MAX_FINDINGS]:
        if f.previous_time_hours is not None and f.previous_time_hours != f.culture_time_hours:
            when = f"{f.previous_time_hours:g}-{f.culture_time_hours:g} h"
        else:
            when = hours(f.culture_time_hours) if f.culture_time_hours is not None else "-"
        rows.append([f.severity.upper(), f.type_label, f.parameter_label or "-", when, f.message])
    return rows


def data_quality_rows(analysis: ExperimentAnalysis, anomalies: AnomalyReport) -> list[list[str]]:
    q = analysis.data_quality
    if q.smallest_interval_hours is None:
        interval = NOT_AVAILABLE
    elif q.smallest_interval_hours == q.largest_interval_hours:
        interval = hours(q.smallest_interval_hours)
    else:
        interval = f"{q.smallest_interval_hours:g} h to {q.largest_interval_hours:g} h"
    missing = [
        f"{m.label}: {'not recorded' if m.missing == q.observation_count else f'missing in {m.missing} of {q.observation_count}'}"
        for m in q.missing_values if m.missing
    ]
    coverage = [f.message for f in anomalies.findings if f.type == "data_coverage"]
    return [
        ["Observations", str(q.observation_count)],
        ["Culture-time range", NOT_AVAILABLE if analysis.culture_start_hours is None
         else f"{analysis.culture_start_hours:g} h to {analysis.culture_end_hours:g} h"],
        ["Distinct time points", str(q.distinct_time_points)],
        ["Repeated time points", str(q.duplicate_time_points)],
        ["Interval between time points", interval],
        ["Missing optional values", "; ".join(missing) or "None"],
        ["Coverage notes", " ".join(coverage) or "None"],
        ["Trend charts", "Available (2 or more distinct time points)" if q.enough_for_trends
         else "Not available: at least 2 distinct time points are needed"],
    ]


# --- PDF rendering ------------------------------------------------------------------------

ACCENT = colors.HexColor("#0d9488")
MUTED = colors.HexColor("#5b6776")
BORDER = colors.HexColor("#dde3ea")
TAG_COLORS = {
    "OBSERVED DATA": "#0f766e", "DETERMINISTIC CALCULATION": "#0f766e",
    "SCENARIO ASSUMPTIONS": "#b45309", "AI INTERPRETATION": "#6d28d9",
}


def _styles():
    base = getSampleStyleSheet()
    s = {
        "project": ParagraphStyle("project", parent=base["Normal"], fontSize=9, textColor=MUTED, spaceAfter=2),
        "title": ParagraphStyle("title", parent=base["Title"], fontSize=18, alignment=TA_LEFT, spaceAfter=8),
        "h1": ParagraphStyle("h1", parent=base["Heading2"], fontSize=13, spaceBefore=12, spaceAfter=4, textColor=colors.HexColor("#1c2430")),
        "h2": ParagraphStyle("h2", parent=base["Heading4"], fontSize=10, spaceBefore=6, spaceAfter=2),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontSize=9, leading=12),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontSize=7.5, leading=9.5, textColor=MUTED),
        "cell": ParagraphStyle("cell", parent=base["BodyText"], fontSize=7.5, leading=9.5),
        "bullet": ParagraphStyle("bullet", parent=base["BodyText"], fontSize=9, leading=12, leftIndent=10, bulletIndent=2),
    }
    return s


def _tag(label: str, note: str, st) -> Paragraph:
    return Paragraph(f'<font color="{TAG_COLORS[label]}"><b>{label}</b></font> - {rich(note)}', st["small"])


def _bullets(items: list[str], st) -> list:
    return [Paragraph(rich(i), st["bullet"], bulletText="•") for i in items]


def _table(rows: list[list[str]], widths: list[float], st, header: bool = True, numeric_from: int | None = None) -> Table:
    data = [[Paragraph(rich(c) if not (header and r == 0) else f"<b>{rich(c)}</b>", st["cell"]) for c in row]
            for r, row in enumerate(rows)]
    table = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f5"))]
    table.setStyle(TableStyle(style))
    return table


def _trend_chart(analysis: ExperimentAnalysis, name: str, min_span: float, width: float, height: float):
    label, unit = _meta(name)
    points = [(o.culture_time_hours, getattr(o, name)) for o in analysis.observations if getattr(o, name) is not None]
    title = f"{label}{f' ({unit})' if unit else ''}"
    if len({t for t, _ in points}) < 2:
        return Paragraph(f"<b>{rich(title)}</b><br/>Insufficient data for trend.", _styles()["body"])
    step = max(1, len(points) // MAX_CHART_POINTS)  # drawing only: every n-th stored point
    shown = points[::step] if points[-1] in points[::step] else points[::step] + [points[-1]]
    lo, hi = min(v for _, v in points), max(v for _, v in points)
    if hi - lo < min_span:
        mid = (hi + lo) / 2
        lo, hi = mid - min_span / 2, mid + min_span / 2
    pad = (hi - lo) * 0.08
    d = Drawing(width, height)
    d.add(String(0, height - 10, plain(title), fontName="Helvetica-Bold", fontSize=8))
    plot = LinePlot()
    plot.x, plot.y, plot.width, plot.height = 32, 18, width - 40, height - 34
    plot.data = [shown]
    plot.lines[0].strokeColor = ACCENT
    plot.lines[0].strokeWidth = 1.2
    plot.xValueAxis.valueMin, plot.xValueAxis.valueMax = shown[0][0], shown[-1][0]
    plot.yValueAxis.valueMin, plot.yValueAxis.valueMax = lo - pad, hi + pad
    for axis in (plot.xValueAxis, plot.yValueAxis):
        axis.labels.fontName = "Helvetica"
        axis.labels.fontSize = 6.5
        axis.labels.fillColor = MUTED
        axis.strokeColor = BORDER
    decimals = PARAMETER_DECIMALS[name]
    plot.yValueAxis.labelTextFormat = lambda v: f"{v:.{min(decimals, 2)}f}"
    plot.xValueAxis.labelTextFormat = lambda v: f"{v:g} h"
    d.add(plot)
    if step > 1:
        d.add(String(width - 4, 2, f"every {step}th point drawn", fontSize=6, fillColor=MUTED, textAnchor="end"))
    return d


def render_pdf(data: ReportData) -> bytes:
    st = _styles()
    a, an = data.analysis, data.anomalies
    exp = a.experiment
    generated = data.generated_at.strftime("%Y-%m-%d %H:%M UTC")
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
        title=f"{REPORT_TITLE} - {exp.experiment_id}", author=PROJECT_NAME, subject=REPORT_TITLE,
    )
    full = doc.width

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(16 * mm, 10 * mm, plain(f"{PROJECT_NAME} - {exp.experiment_id} - generated {generated}"))
        canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, f"Page {document.page}")
        canvas.restoreState()

    story: list = [
        Paragraph(rich(PROJECT_NAME.upper()), st["project"]),
        Paragraph(rich(REPORT_TITLE), st["title"]),
        _table([["Experiment", exp.experiment_id], ["Name", exp.name], ["Scale", f"{exp.scale_liters:g} L"],
                ["Data source", exp.data_source.value.upper()], ["Generated", generated]],
               [35 * mm, full - 35 * mm], st, header=False),
    ]
    if exp.data_source == DataSource.SIMULATED:
        story += [Spacer(1, 4), Paragraph(
            "<b>Simulated data.</b> This experiment contains software-generated values, not laboratory measurements.", st["body"])]

    # 1. Executive overview
    available = [f"{p.label} (n={p.count})" for p in a.parameters]
    counts = an.counts
    story += [
        Paragraph("1. Executive Overview", st["h1"]),
        _tag("DETERMINISTIC CALCULATION", "calculated by the application from the stored observations.", st),
        *_bullets([
            f"Observations: {a.observation_count}",
            f"Culture duration: {hours(a.culture_duration_hours)} "
            f"(start {hours(a.culture_start_hours)}, end {hours(a.culture_end_hours)})",
            f"Parameters with data: {', '.join(available) if available else 'none'}",
            f"Data quality: {a.data_quality.distinct_time_points} distinct time point(s), "
            f"{a.data_quality.duplicate_time_points} repeated; trend charts "
            f"{'available' if a.data_quality.enough_for_trends else 'not available'}",
            f"Anomaly findings: {an.finding_count} ({counts.significant} significant, {counts.attention} attention, {counts.info} info)",
        ], st),
        Paragraph("<b>Factual process summary</b>", st["h2"]),
        *_bullets(a.summary, st),
    ]

    # 2. Experiment details
    story += [
        Paragraph("2. Experiment Details", st["h1"]),
        _tag("OBSERVED DATA", "experiment metadata as stored.", st),
        _table([["Experiment ID", exp.experiment_id], ["Name", exp.name],
                ["Description", exp.description or NOT_AVAILABLE], ["Scale (working volume)", f"{exp.scale_liters:g} L"],
                ["Data source", exp.data_source.value.upper()],
                ["Created", exp.created_at.strftime("%Y-%m-%d %H:%M UTC")], ["Notes", exp.notes or NOT_AVAILABLE]],
               [45 * mm, full - 45 * mm], st, header=False),
    ]

    # 3. Process statistics
    widths = [36 * mm, 22 * mm, 9 * mm] + [(full - 67 * mm) / 6] * 6
    rows = parameter_rows(a)
    display = [row[:3] + ([f"{NOT_AVAILABLE}: no observations of this parameter", "", "", "", "", ""]
                          if row[3:] == [NOT_AVAILABLE] * 6 else row[3:]) for row in rows]
    stats = _table([["Parameter", "Unit", "n", "Start", "Final", "Min", "Max", "Average", "Delta"], *display], widths, st)
    stats.setStyle(TableStyle([("SPAN", (3, i), (8, i)) for i, row in enumerate(rows, start=1) if row[3:] == [NOT_AVAILABLE] * 6]))
    story += [
        Paragraph("3. Process Statistics", st["h1"]),
        _tag("DETERMINISTIC CALCULATION", "start/final are the first/last recorded values; delta = final - start. "
             "Values are rounded for display only.", st),
        stats,
    ]

    # 4. Trends
    col = (full - 6 * mm) / 2
    cells = [_trend_chart(a, name, span, col, 52 * mm) for name, span in TREND_PARAMETERS]
    grid = [cells[i:i + 2] + ([""] if len(cells[i:i + 2]) == 1 else []) for i in range(0, len(cells), 2)]
    trend_table = Table(grid, colWidths=[col, col], hAlign="LEFT")
    trend_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [
        Paragraph("4. Process Trends", st["h1"]),
        _tag("OBSERVED DATA", "stored observations plotted against culture time; no values are interpolated or invented.", st),
        trend_table,
    ]

    # 5. Data quality
    story += [
        Paragraph("5. Data Quality", st["h1"]),
        _tag("DETERMINISTIC CALCULATION", "coverage of the stored observations.", st),
        _table(data_quality_rows(a, an), [45 * mm, full - 45 * mm], st, header=False),
    ]

    # 6. Findings
    story += [
        Paragraph("6. Anomaly / Findings", st["h1"]),
        _tag("DETERMINISTIC CALCULATION", "rule-based findings using prototype monitoring ranges and thresholds "
             "(application rules, not universal biological limits). Severity labels are display categories.", st),
    ]
    if a.observation_count == 0:
        story.append(Paragraph("No observations have been recorded, so no checks were run.", st["body"]))
    elif not an.findings:
        story.append(Paragraph("No findings with the prototype monitoring configuration.", st["body"]))
    else:
        story += [
            Paragraph(rich(f"{an.finding_count} finding(s): {counts.significant} significant, {counts.attention} attention, "
                           f"{counts.info} info."), st["body"]),
            Spacer(1, 3),
            _table([["Severity", "Type", "Parameter", "Culture time", "Finding"], *finding_rows(an)],
                   [24 * mm, 30 * mm, 24 * mm, 19 * mm, full - 97 * mm], st),
        ]
        if an.finding_count > MAX_FINDINGS:
            story.append(Paragraph(f"{an.finding_count - MAX_FINDINGS} further finding(s) not listed.", st["small"]))

    # 7. Scale-up scenario
    story.append(Paragraph("7. Scale-Up Scenario", st["h1"]))
    su = data.scale_up
    if su is None:
        story.append(Paragraph("Scale-up scenario not included.", st["body"]))
    else:
        g, f = su.gas_flow, su.feed
        story += [
            _tag("SCENARIO ASSUMPTIONS", "illustrative calculations from user-chosen settings; not a prediction of "
                 "real biological performance.", st),
            Paragraph(rich(su.disclaimer), st["small"]),
            Spacer(1, 3),
            _table([
                ["Source scale", f"{su.source.scale_liters:g} L"],
                ["Target scale", f"{su.target_scale_liters:g} L"],
                ["Scale factor (target / source)", f"{su.scale_factor:,.3g}×"],
                ["Volume increase", f"{su.volume_increase_liters:,.3g} L"],
                ["Gas flow, source (vvm × volume)", NOT_AVAILABLE if g.source_l_per_min is None
                 else f"{g.source_vvm:g} vvm × {su.source.scale_liters:g} L = {g.source_l_per_min:,.3g} L/min"],
                ["Gas flow, target (vvm × volume)", NOT_AVAILABLE if g.target_l_per_min is None
                 else f"{g.target_vvm:g} vvm × {su.target_scale_liters:g} L = {g.target_l_per_min:,.3g} L/min ({g.target_l_per_h:,.4g} L/h)"],
                ["Feed per litre, source / target", NOT_AVAILABLE
                 if f.source_ml_per_h_per_l is None and f.target_ml_per_h_per_l is None
                 else f"{fmt(f.source_ml_per_h_per_l, 3)} / {fmt(f.target_ml_per_h_per_l, 3)} mL/h per L"],
                ["Same feed per litre at target", NOT_AVAILABLE if f.volume_proportional_ml_per_h is None
                 else f"{f.volume_proportional_ml_per_h:,.4g} mL/h"],
                ["Total feed over baseline duration", NOT_AVAILABLE if f.target_total_feed_ml is None
                 else f"{f.target_total_feed_ml:,.4g} mL over {f.baseline_duration_hours:g} h (constant rate)"],
            ], [60 * mm, full - 60 * mm], st, header=False),
            Spacer(1, 4),
            _table([["Parameter", "Source", "Target scenario", "Change", "Treatment"]] + [
                [p.label,
                 NOT_AVAILABLE if p.source is None else f"{p.source:g}{' ' + p.unit if p.unit else ''}",
                 NOT_AVAILABLE if p.target is None else f"{p.target:g}{' ' + p.unit if p.unit else ''}",
                 NOT_AVAILABLE if p.change is None else f"{p.change:+g}",
                 p.treatment]
                for p in su.parameters
            ], [36 * mm, 34 * mm, 34 * mm, 22 * mm, full - 126 * mm], st),
            Paragraph("Preserved = kept at the source value; Scenario setting = user-chosen value; Baseline assumption = "
                      "carried over from the source, not predicted; Not available = no source value or target.", st["small"]),
            Paragraph("<b>Not calculated (requires engineering validation)</b>", st["h2"]),
            *_bullets(su.considerations, st),
        ]

    # 8. AI analysis
    story.append(Paragraph("8. AI Analysis", st["h1"]))
    ai = data.ai_analysis
    if ai is None:
        story.append(Paragraph("AI analysis not included.", st["body"]))
    else:
        x = ai.analysis
        story += [
            _tag("AI INTERPRETATION", "AI-generated interpretation of application data; not experimental fact. "
                 "Review by a scientist is required.", st),
            Paragraph(rich(f"Generated by {ai.model or 'Gemini'}"
                           + (f" at {ai.generated_at.strftime('%Y-%m-%d %H:%M UTC')}" if ai.generated_at else "")), st["small"]),
            Paragraph("<b>Overview</b>", st["h2"]), Paragraph(rich(x.overview), st["body"]),
        ]
        if x.observed_patterns:
            story += [Paragraph("<b>Observed patterns</b>", st["h2"]),
                      *_bullets([f"{p.title}: {p.observation} (evidence: {p.evidence})" for p in x.observed_patterns], st)]
        if x.possible_interpretations:
            story += [Paragraph("<b>Possible interpretations</b>", st["h2"]),
                      *_bullets([f"{p.title}: {p.interpretation} Supporting evidence: {p.supporting_evidence} "
                                 f"Uncertainty: {p.uncertainty}" for p in x.possible_interpretations], st)]
        if x.attention_points:
            story += [Paragraph("<b>Attention points</b>", st["h2"]),
                      *_bullets([f"{p.title} [{p.finding_type}]: {p.explanation}" for p in x.attention_points], st)]
        if x.scale_up_considerations:
            story += [Paragraph("<b>Scale-up considerations</b>", st["h2"]),
                      *_bullets([f"{p.title}: {p.consideration} (basis: {p.basis})" for p in x.scale_up_considerations], st)]
        if x.questions_for_investigation:
            story += [Paragraph("<b>Questions for further investigation</b>", st["h2"]), *_bullets(x.questions_for_investigation, st)]
        story.append(Paragraph("Limitations: AI output may be incomplete or incorrect; measurements and deterministic "
                               "findings in sections 1-6 are the reference.", st["small"]))

    # 9. AI Copilot
    story.append(Paragraph("9. AI Copilot", st["h1"]))
    cp = data.copilot
    if cp is None:
        story.append(Paragraph("AI Copilot response not included.", st["body"]))
    else:
        story += [
            _tag("AI INTERPRETATION", "AI Copilot response (AI-generated). Only the latest response from this session "
                 "is included; no conversation history is stored.", st),
            Paragraph(rich(f"Generated by {cp.model or 'Gemini'}"
                           + (f" at {cp.generated_at.strftime('%Y-%m-%d %H:%M UTC')}" if cp.generated_at else "")), st["small"]),
            Paragraph(f"<b>Question:</b> {rich(cp.question)}", st["body"]),
            Paragraph(f"<b>Answer:</b> {rich(cp.answer)}", st["body"]),
        ]
        for title, items in (("Evidence", cp.evidence), ("Uncertainties", cp.uncertainties),
                             ("Suggested follow-up questions", cp.suggested_questions)):
            if items:
                story += [Paragraph(f"<b>{title}</b>", st["h2"]), *_bullets(items, st)]

    # 10. Limitations
    story += [KeepTogether([Paragraph("10. Limitations", st["h1"]), *_bullets(LIMITATIONS, st)])]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def report_filename(experiment_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in experiment_id)
    return f"bioprocess-report-{safe}.pdf"
