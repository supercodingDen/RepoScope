import { PROJECT } from "./recording";

export function Architecture() {
  return (
    <section className="panel-page">
      <p className="eyebrow">SYSTEM DESIGN</p>
      <h2>Small services. Durable work.</h2>
      <p className="panel-intro">
        One Python application, three independent roles. PostgreSQL owns state;
        workers recover work through durable events.
      </p>
      <div className="architecture" aria-label="System architecture">
        <div className="arch-node">
          <span>01 / REQUEST</span>
          <strong>FastAPI</strong>
          <p>
            Authenticated admission
            <br />
            Idempotency + pinned revision
          </p>
        </div>
        <div className="arch-arrow" aria-hidden="true">
          →
        </div>
        <div className="arch-node accent">
          <span>02 / COMMIT</span>
          <strong>Transactional outbox</strong>
          <p>
            Job + event in one transaction
            <br />
            PostgreSQL / pgvector
          </p>
        </div>
        <div className="arch-arrow" aria-hidden="true">
          →
        </div>
        <div className="arch-node">
          <span>03 / DELIVER</span>
          <strong>NATS JetStream</strong>
          <p>
            Indexer + read-only agent
            <br />
            Leases, fencing, bounded retries
          </p>
        </div>
      </div>
      <div className="detail-grid">
        <article>
          <span className="small-label">RETRIEVAL</span>
          <h3>Find evidence before answering</h3>
          <p>
            Bounded source acquisition → AST-aware chunks → embeddings →
            pgvector + PostgreSQL full-text search → reciprocal-rank fusion.
          </p>
          <p>
            The lexical branch uses PostgreSQL full-text search; this project
            does not claim a BM25 implementation.
          </p>
        </article>
        <article>
          <span className="small-label">AGENT</span>
          <h3>Three tools, one pinned scope</h3>
          <p>
            <code>search_code</code>, <code>get_file</code>, and{" "}
            <code>get_repository_summary</code>. Six tool steps maximum, bounded
            context, one-hop dependency expansion.
          </p>
          <p>Imported repository code is never executed.</p>
        </article>
        <article>
          <span className="small-label">RELIABILITY</span>
          <h3>Progress survives the connection</h3>
          <p>
            Run events persist in PostgreSQL. Authenticated SSE resumes after a
            validated cursor. Redis is disposable admission/cache state.
          </p>
          <p>Model-call spend uses atomic reservations in live mode.</p>
        </article>
      </div>
      <a
        className="text-link"
        href={`${PROJECT}/blob/main/docs/architecture.md`}
        target="_blank"
        rel="noreferrer"
      >
        Explore the architecture and trade-offs ↗
      </a>
    </section>
  );
}

export function Evaluation() {
  const trials = [
    { trial: 1, p95: 444.611, qps: 79.762 },
    { trial: 2, p95: 438.126, qps: 80.173 },
    { trial: 3, p95: 442.384, qps: 80.046 },
  ];
  return (
    <section className="panel-page">
      <p className="eyebrow">MEASURED, WITH LIMITS</p>
      <h2>Show the workload. Keep the caveats.</h2>
      <p className="panel-intro">
        Historical T12 benchmark · 2026-09-24 · 100,029 real source chunks · 200
        fixed queries · 32 active clients · mock embeddings.
      </p>
      <div className="metric-grid">
        <article>
          <strong>100,029</strong>
          <span>real source chunks</span>
        </article>
        <article>
          <strong>~80</strong>
          <span>search queries / second</span>
        </article>
        <article>
          <strong>0.9235</strong>
          <span>Recall@10 vs. exact mock-vector neighbors</span>
        </article>
      </div>
      <div className="evaluation-grid">
        <article className="chart-card">
          <div className="section-title">
            <h3>Search latency · p95</h3>
            <span className="badge amber">Target not met</span>
          </div>
          <p>100 ms target. Three 60-second trials; lower is better.</p>
          <div
            className="bar-chart"
            role="img"
            aria-label="Three measured p95 latencies: 444.611, 438.126, and 442.384 milliseconds; each exceeds the 100 millisecond target."
          >
            <div className="target-line" aria-hidden="true">
              <span>100 ms target</span>
            </div>
            {trials.map((t) => (
              <div className="bar-row" key={t.trial}>
                <span>Trial {t.trial}</span>
                <div className="bar-track">
                  <div className="bar" style={{ width: `${t.p95 / 5}%` }} />
                </div>
                <b>{t.p95.toFixed(1)} ms</b>
              </div>
            ))}
          </div>
          <table>
            <caption>Raw trial summaries</caption>
            <thead>
              <tr>
                <th>Trial</th>
                <th>p95 (ms)</th>
                <th>QPS</th>
              </tr>
            </thead>
            <tbody>
              {trials.map((t) => (
                <tr key={t.trial}>
                  <td>{t.trial}</td>
                  <td>{t.p95}</td>
                  <td>{t.qps}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </article>
        <article className="honesty-card">
          <span className="small-label">WHAT THESE NUMBERS MEAN</span>
          <h3>Retrieval mechanics, not answer quality.</h3>
          <p>
            ANN Recall@10 compares approximate neighbors with exact neighbors in
            a deterministic mock-vector space. It is not semantic answer
            accuracy.
          </p>
          <p>
            Live embeddings, a human-reviewed question set, grounded answer
            assessment, and paid-provider latency remain unmeasured.
          </p>
          <p>
            The recording's mock agent selects the first retrieved excerpt. A
            citation locates its source; it does not establish that the answer
            is correct.
          </p>
        </article>
      </div>
      <p className="source-note">
        Evidence:{" "}
        <a
          href={`${PROJECT}/blob/main/bench/data/t12-final-420-pool10.json`}
          target="_blank"
          rel="noreferrer"
        >
          three application trials ↗
        </a>{" "}
        ·{" "}
        <a
          href={`${PROJECT}/blob/main/bench/data/t12-unfiltered-420.json`}
          target="_blank"
          rel="noreferrer"
        >
          mock-vector recall ↗
        </a>{" "}
        ·{" "}
        <a
          href={`${PROJECT}/blob/main/docs/t12-performance.md`}
          target="_blank"
          rel="noreferrer"
        >
          workload and hardware ↗
        </a>
        . These historical measurements are separate from this small-repository
        recording.
      </p>
    </section>
  );
}

export function Reproduce() {
  return (
    <section className="panel-page">
      <p className="eyebrow">TAKE IT APART</p>
      <h2>A recording you can reproduce.</h2>
      <p className="panel-intro">
        The public page is a static evidence browser. The Python backend runs
        separately on your machine; no API key is needed for mock mode.
      </p>
      <div className="detail-grid">
        <article>
          <span className="small-label">01 / INSPECT</span>
          <h3>Read the recording</h3>
          <p>
            Open the versioned JSON, inspect the pinned commit and event
            sequences, and follow every source citation.
          </p>
          <a
            className="text-link"
            href="./recordings/demo.json"
            target="_blank"
            rel="noreferrer"
          >
            Open recording JSON ↗
          </a>
        </article>
        <article>
          <span className="small-label">02 / REPLAY LOCALLY</span>
          <h3>Run the same backend</h3>
          <p>
            Use Docker Compose, Python, and the existing CLI. Source acquisition
            happens without running the imported repository's code.
          </p>
          <a
            className="text-link"
            href={`${PROJECT}/blob/main/docs/demo.md`}
            target="_blank"
            rel="noreferrer"
          >
            Local walkthrough ↗
          </a>
        </article>
        <article>
          <span className="small-label">03 / CAPTURE AGAIN</span>
          <h3>Export a fresh session</h3>
          <p>
            The exporter creates disposable volumes, disables dotenv and paid
            providers, checks citations and cursor continuity, and writes only
            validated public fields.
          </p>
          <a
            className="text-link"
            href={`${PROJECT}/blob/main/docs/interactive-demo.md`}
            target="_blank"
            rel="noreferrer"
          >
            Capture and development guide ↗
          </a>
        </article>
      </div>
      <div className="boundary-note">
        <strong>Live AI is a separate next step.</strong>
        <p>
          Configure credentials only in protected local/host files, explicitly
          opt in to paid calls, and record a reviewed evaluation. This page
          never asks visitors for tokens or sends questions to a model.
        </p>
      </div>
    </section>
  );
}
