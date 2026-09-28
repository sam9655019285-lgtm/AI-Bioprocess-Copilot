/*
 * Investigation workflow handoff (Phase 22): one explicit "next step" button per page.
 * Presentation only — it calls the existing onNavigate; no data fetching, no state,
 * no calculations and never an AI request. The destination page keeps its own selection.
 */
export default function NextStep({ stage, label, page, hint, onNavigate }) {
  if (!onNavigate) return null
  return (
    <div className="next-step" data-testid="next-step">
      <div className="next-step-text">
        <span className="next-step-stage">Next · {stage}</span>
        {hint && <span className="next-step-hint">{hint}</span>}
      </div>
      <button type="button" className="secondary next-step-button" onClick={() => onNavigate(page)}>
        {label}
      </button>
    </div>
  )
}
