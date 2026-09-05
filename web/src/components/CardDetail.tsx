import type { CardDetail as Detail } from "../types";

/** The card as the CLI renders it, plus the two things a reviewer needs to
 *  judge it: what was cited, and what the loop actually did to get there. */
export function CardView({ detail }: { detail: Detail }) {
  const card = detail.card;
  const { root_cause: rootCause, run } = card;

  return (
    <>
      <section className="panel">
        <h2>Verdict</h2>
        <dl className="verdict">
          <dt>incident</dt>
          <dd className="mono">
            {card.incident.dag_id}/{card.incident.task_id}/{card.incident.run_id}#
            {card.incident.try_number}
          </dd>

          <dt>root cause</dt>
          <dd>
            <span className="chip category">{rootCause.category}</span>
          </dd>

          <dt>confidence</dt>
          <dd>
            <div className="row">
              <div className="meter" style={{ width: 220 }}>
                <span style={{ width: `${Math.round(rootCause.confidence * 100)}%` }} />
              </div>
              <span className="mono">{rootCause.confidence.toFixed(2)}</span>
            </div>
          </dd>

          <dt>hypothesis</dt>
          <dd>{rootCause.hypothesis}</dd>

          <dt>suggested fix</dt>
          <dd>{card.suggested_fix}</dd>

          <dt>flags</dt>
          <dd className="row">
            {card.security_flags.length === 0 && <span className="muted">none</span>}
            {card.security_flags.map((flag) => (
              <span key={flag} className="chip bad">
                {flag}
              </span>
            ))}
            {card.insufficient_evidence && <span className="chip warn">insufficient evidence</span>}
            {card.parse_error && <span className="chip bad">parse error</span>}
          </dd>
        </dl>
        <p className="muted mono" style={{ marginBottom: 0 }}>
          {run.model} · {run.mode} · {run.steps_used}/{run.max_steps} steps · {run.latency_ms} ms ·
          ${run.cost_usd.toFixed(4)}
        </p>
      </section>

      <section className="panel">
        <h2>Citations ({card.citations.length})</h2>
        {card.citations.length === 0 ? (
          <p className="muted">
            No grounded citations. Every citation on a card resolved to a chunk that was in
            context during this run; ones that did not were dropped.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>source</th>
                <th>chunk</th>
                <th>quote</th>
              </tr>
            </thead>
            <tbody>
              {card.citations.map((citation, index) => (
                <tr key={`${citation.chunk_id}-${index}`}>
                  <td className="mono wrap">{citation.source}</td>
                  <td className="mono wrap">{citation.chunk_id}</td>
                  <td className="wrap">
                    <blockquote>{citation.quote}</blockquote>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <h2>Evidence trail ({card.evidence_trail.length} steps)</h2>
        {card.evidence_trail.length === 0 ? (
          <p className="muted">No tool calls — this card came from a single-shot run.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>tool</th>
                <th>args</th>
                <th>result</th>
              </tr>
            </thead>
            <tbody>
              {card.evidence_trail.map((step) => (
                <tr key={step.step + step.tool}>
                  <td className="mono">{step.step}</td>
                  <td className="mono">{step.tool}</td>
                  <td className="mono wrap">{JSON.stringify(step.args)}</td>
                  <td className="wrap">
                    {step.error ? (
                      <span className="chip bad">{step.error}</span>
                    ) : (
                      <span className="muted mono">{step.result_digest}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
