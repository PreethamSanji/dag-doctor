import type { EvalReport } from "../types";

function format(value: number | null): string {
  if (value === null) return "n/a";
  return Math.abs(value) >= 1000 ? value.toFixed(0) : value.toFixed(3);
}

/** The latest eval report, read from `evals/reports/latest/report.json`. The
 *  gate's verdict is shown as-is: a partial run reports without gating. */
export function EvalPanel({ report }: { report: EvalReport }) {
  if (!report.available || !report.gate) {
    return (
      <p className="muted">
        No eval report yet. Run <code className="mono">triage eval</code>.
      </p>
    );
  }

  const { gate } = report;
  const status = !gate.enforced ? "report only" : gate.passed ? "pass" : "fail";
  const tone = !gate.enforced ? "warn" : gate.passed ? "ok" : "bad";

  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <span className={`chip ${tone}`}>gate: {status}</span>
        <span className="muted mono">{report.created_at?.slice(0, 19).replace("T", " ")}</span>
      </div>
      {!gate.enforced && <p className="muted">{gate.reason}</p>}

      <table>
        <thead>
          <tr>
            <th>metric</th>
            <th>value</th>
            <th>threshold</th>
          </tr>
        </thead>
        <tbody>
          {gate.checks.map((check) => (
            <tr key={`${check.metric}-${check.kind}`}>
              <td className="mono">{check.metric}</td>
              <td className="mono">{format(check.value)}</td>
              <td className="mono">
                <span className={`chip ${check.skipped ? "" : check.passed ? "ok" : "bad"}`}>
                  {check.kind === "min" ? "≥" : "≤"} {check.bound}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="muted mono" style={{ marginBottom: 0 }}>
        {JSON.stringify(report.config_fingerprint)}
      </p>
    </>
  );
}
