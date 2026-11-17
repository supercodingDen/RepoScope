import { useEffect, useState } from "react";
import { Architecture, Evaluation, Reproduce } from "./Panels";
import { loadRecording, PROJECT, sourceLink } from "./recording";
import type { DemoCase, Match, Recording, RunEvent } from "./recording";

function eventLabel(event: RunEvent): string {
  if (event.data.kind === "run.started") return "Run accepted · mock provider";
  if (event.data.kind === "run.completed") return "Cited result persisted";
  return `${event.data.tool} · ${event.data.kind === "tool.started" ? "started" : "completed"}`;
}

function Workbench({ item }: { item: DemoCase }) {
  const [selectedId, setSelectedId] = useState(
    item.result.citations[0]?.chunk_id ?? item.search.results[0]?.chunk_id,
  );
  const [count, setCount] = useState(0);
  const [playing, setPlaying] = useState(false);
  const selected: Match | undefined = item.search.results.find(
    (m) => m.chunk_id === selectedId,
  );
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(
      () =>
        setCount((previous) => {
          if (previous >= item.events.length - 1) {
            setPlaying(false);
            return item.events.length;
          }
          return previous + 1;
        }),
      800,
    );
    return () => window.clearInterval(timer);
  }, [playing, item.events.length]);
  const firstTime = Date.parse(item.events[0]?.occurred_at ?? "");
  return (
    <div className="workbench-body">
      {item.path_prefix && (
        <p className="scope-disclosure">
          Scope applies only to the recorded search below. Agent output and tool
          events come from an unfiltered run.
        </p>
      )}
      <div className="query-strip">
        <div>
          <span className="small-label">RECORDED QUERY</span>
          <h3>{item.question}</h3>
        </div>
        <div className="scope-pill">
          {item.path_prefix ?? "All indexed paths"}
        </div>
      </div>
      <div className="replay-strip">
        <div className="replay-controls">
          <button
            className="primary-button"
            onClick={() => {
              if (count === item.events.length) setCount(0);
              setPlaying(!playing);
            }}
          >
            {playing ? "Pause playback" : "Play recording"}
          </button>
          <button
            className="quiet-button"
            onClick={() => {
              setPlaying(false);
              setCount(Math.min(count + 1, item.events.length));
            }}
            disabled={count === item.events.length}
          >
            Next event
          </button>
          <button
            className="icon-button"
            aria-label="Reset playback"
            onClick={() => {
              setPlaying(false);
              setCount(0);
            }}
          >
            ↺
          </button>
        </div>
        <span
          className="mono"
          data-testid="playback-progress"
          aria-live="polite"
        >
          {count} / {item.events.length} events
        </span>
      </div>
      <div className="evidence-grid">
        <div className="results-column">
          <div className="section-title">
            <h3>Retrieved evidence</h3>
            <span className="badge">{item.search.results.length} matches</span>
          </div>
          <p className="muted tiny">
            Vector + full-text → RRF. Scores are ranks, not confidence.
          </p>
          <div className="results-list">
            {item.search.results.map((match, index) => (
              <button
                key={match.chunk_id}
                className={`result-card ${selectedId === match.chunk_id ? "selected" : ""}`}
                aria-pressed={selectedId === match.chunk_id}
                onClick={() => setSelectedId(match.chunk_id)}
              >
                <span className="rank">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="result-info">
                  <strong>{match.path.split("/").at(-1)}</strong>
                  <span className="path">{match.path}</span>
                  <span className="result-meta">
                    L{match.start_line}–{match.end_line}
                    <span>RRF {match.score.toFixed(4)}</span>
                  </span>
                </span>
                <span aria-hidden="true">↗</span>
              </button>
            ))}
          </div>
          <div className="search-timing">
            <span className="status-dot" /> {item.search.duration_ms.toFixed(1)}{" "}
            ms recorded search · one request
          </div>
        </div>
        <div className="source-column">
          <div className="source-toolbar">
            <div>
              <span className="small-label">PINNED SOURCE</span>
              <p>{selected?.path ?? "Select evidence"}</p>
            </div>
            <span className="commit-tag">672971d</span>
          </div>
          <div
            className="code-view"
            tabIndex={0}
            aria-label="Recorded source excerpt"
          >
            {selected?.content
              .replace(/\n$/, "")
              .split("\n")
              .map((line, index) => (
                <div className="code-line" key={index}>
                  <span className="line-number" aria-hidden="true">
                    {selected.start_line + index}
                  </span>
                  <code>{line || " "}</code>
                </div>
              ))}
          </div>
          {selected && (
            <a
              className="source-link"
              href={sourceLink(selected)}
              target="_blank"
              rel="noreferrer"
            >
              Open pinned source on GitHub <span aria-hidden="true">↗</span>
            </a>
          )}
          <div className="answer-card">
            <div className="section-title">
              <h3>Recorded mock output</h3>
              <span className="badge">$0.00 · mock</span>
            </div>
            <p className="recorded-answer">{item.result.answer}</p>
            <div className="citation-row">
              {item.result.citations.map((citation, index) => (
                <button
                  key={citation.chunk_id}
                  aria-label={`View citation ${index + 1}`}
                  onClick={() => setSelectedId(citation.chunk_id)}
                >
                  ↗ Citation {index + 1} · L{citation.start_line}–
                  {citation.end_line}
                </button>
              ))}
            </div>
            <p className="tiny muted">
              An excerpt from the first match; answer relevance has not been
              evaluated.
            </p>
          </div>
        </div>
      </div>
      <div className="timeline">
        <div className="section-title">
          <h3>Persisted execution events</h3>
          <span className="tiny muted">
            Playback uses an 800 ms presentation pace; timestamps below are
            measured.
          </span>
        </div>
        <ol>
          {item.events.map((event, index) => (
            <li
              key={event.sequence}
              className={index < count ? "revealed" : ""}
            >
              <span className="event-dot">
                {index < count ? "✓" : event.sequence}
              </span>
              <span>
                <strong>{eventLabel(event)}</strong>
                <small>
                  #{event.sequence} · +
                  {(Date.parse(event.occurred_at) - firstTime).toFixed(0)} ms
                </small>
              </span>
            </li>
          ))}
        </ol>
        {item.resume_after !== null && (
          <div className="resume-proof">
            <span className="badge green">Verified reconnect</span>
            <p>
              Connection closed after event {item.resume_after}. Reconnected
              with <code>Last-Event-ID</code>; received events{" "}
              {item.resumed_sequences.join(", ")} with no duplicates or gaps.
              This demonstrates stream recovery, not worker failover.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function Demo({ recording }: { recording: Recording }) {
  const [caseId, setCaseId] = useState("lookup");
  const [tab, setTab] = useState("Workbench");
  const item =
    recording.cases.find((c) => c.id === caseId) ?? recording.cases[0];
  if (!item) return null;
  return (
    <>
      <section className="hero">
        <div>
          <p className="eyebrow">
            <span className="status-dot" /> AN INTERACTIVE ENGINEERING
            WALKTHROUGH
          </p>
          <h1>
            Understand the code.
            <br />
            <span>Verify the evidence.</span>
          </h1>
          <p className="hero-copy">
            From a repository snapshot to a cited result.
            <br className="desktop-break" /> Inspect retrieval, follow the
            tools, and trace every source.
          </p>
          <div className="hero-badges">
            <span className="badge green">Recorded session</span>
            <span className="badge">Mock model + embeddings</span>
            <span className="tiny muted">No login. No API key.</span>
          </div>
        </div>
        <aside className="snapshot-card">
          <div className="snapshot-header">
            <span className="repo-icon" aria-hidden="true">
              ⌘
            </span>
            <span>
              pallets / <strong>itsdangerous</strong>
            </span>
            <span className="badge">Public source</span>
          </div>
          <div className="snapshot-tree">
            <span>src/itsdangerous/</span>
            <span>├── signer.py</span>
            <span>├── serializer.py</span>
            <span>└── url_safe.py</span>
          </div>
          <div className="snapshot-footer">
            <span className="status-dot" /> Immutable snapshot{" "}
            <code>672971d</code>
          </div>
        </aside>
      </section>
      <section
        className="demo-shell"
        id="demo"
        tabIndex={-1}
        aria-label="Interactive recorded demo"
      >
        <div className="workspace-top">
          <div className="workspace-label">
            <span className="status-dot" /> EVIDENCE WORKSPACE
          </div>
          <div className="tabs" role="tablist" aria-label="Demo views">
            {["Workbench", "Architecture", "Evaluation", "Reproduce"].map(
              (name) => (
                <button
                  key={name}
                  id={`tab-${name}`}
                  role="tab"
                  aria-selected={tab === name}
                  aria-controls={tab === name ? `panel-${name}` : undefined}
                  tabIndex={tab === name ? 0 : -1}
                  onKeyDown={(event) => {
                    const names = [
                      "Workbench",
                      "Architecture",
                      "Evaluation",
                      "Reproduce",
                    ];
                    const direction =
                      event.key === "ArrowRight"
                        ? 1
                        : event.key === "ArrowLeft"
                          ? -1
                          : 0;
                    const index =
                      event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? 3
                          : (names.indexOf(tab) + direction + 4) % 4;
                    const next = names[index];
                    if (
                      (direction ||
                        event.key === "Home" ||
                        event.key === "End") &&
                      next
                    ) {
                      event.preventDefault();
                      setTab(next);
                      document.getElementById(`tab-${next}`)?.focus();
                    }
                  }}
                  onClick={() => setTab(name)}
                >
                  {name}
                </button>
              ),
            )}
          </div>
        </div>
        <div
          role="tabpanel"
          id={`panel-${tab}`}
          aria-labelledby={`tab-${tab}`}
          tabIndex={0}
        >
          {tab === "Workbench" ? (
            <div className="workspace-grid">
              <aside className="case-sidebar">
                <p className="small-label">EXPLORE THREE CASES</p>
                {recording.cases.map((c, index) => (
                  <button
                    className={`case-button ${c.id === item.id ? "active" : ""}`}
                    key={c.id}
                    aria-pressed={c.id === item.id}
                    onClick={() => setCaseId(c.id)}
                  >
                    <span className="case-number">0{index + 1}</span>
                    <strong>{c.title}</strong>
                    <small>
                      {index === 0
                        ? "Query → ranked source"
                        : index === 1
                          ? "Constrain the search path"
                          : "Close → reconnect → continue"}
                    </small>
                  </button>
                ))}
                <div className="sidebar-note">
                  <span className="small-label">REPLAY, THEN REPRODUCE</span>
                  <p>
                    These are captured backend responses, not a live chatbot.
                    Every displayed tool event occurred in the recorded run.
                  </p>
                </div>
              </aside>
              <Workbench key={item.id} item={item} />
            </div>
          ) : tab === "Architecture" ? (
            <Architecture />
          ) : tab === "Evaluation" ? (
            <Evaluation />
          ) : (
            <Reproduce />
          )}
        </div>
      </section>
      <div className="provenance-strip">
        <span>
          Recorded {new Date(recording.recorded_at).toISOString().slice(0, 10)}{" "}
          UTC
        </span>
        <span>
          Backend{" "}
          <a
            href={`${PROJECT}/commit/${recording.application_commit}`}
            target="_blank"
            rel="noreferrer"
          >
            {recording.application_commit.slice(0, 7)} ↗
          </a>
        </span>
        <span>
          Source fixed at{" "}
          <a
            href={`https://github.com/pallets/itsdangerous/tree/${recording.commit_sha}`}
            target="_blank"
            rel="noreferrer"
          >
            {recording.commit_sha.slice(0, 7)} ↗
          </a>
        </span>
        <a
          href="./recordings/LICENSE.itsdangerous.txt"
          target="_blank"
          rel="noreferrer"
        >
          Source license ↗
        </a>
      </div>
      <section className="closing-note">
        <span className="small-label">BUILT TO BE INSPECTED</span>
        <p>
          Durable jobs. Scoped retrieval. Bounded tools. Immutable citations.
        </p>
        <span>
          Public source and static demo · Backend hosting and live-model
          evaluation remain separate milestones.
        </span>
      </section>
    </>
  );
}

export default function App() {
  const [recording, setRecording] = useState<Recording | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    void loadRecording()
      .then((data) => {
        if (active) setRecording(data);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, []);
  return (
    <>
      <a className="skip-link" href="#demo">
        Skip to demo
      </a>
      <header className="site-header">
        <a className="brand" href="./" aria-label="RepoScope home">
          <span className="brand-mark" aria-hidden="true">
            r<span>·</span>
          </span>
          RepoScope<span className="brand-divider">/</span>
          <span className="brand-subtitle">CODE INTELLIGENCE</span>
        </a>
        <a
          className="github-link"
          href={PROJECT}
          target="_blank"
          rel="noreferrer"
        >
          View source <span aria-hidden="true">↗</span>
        </a>
      </header>
      <main>
        {failed ? (
          <section className="load-state" role="alert">
            <h1>Recording unavailable</h1>
            <p>
              The recording could not be loaded or validated. No unverified data
              is displayed.
            </p>
            <button
              className="primary-button"
              onClick={() => window.location.reload()}
            >
              Reload page
            </button>
          </section>
        ) : recording ? (
          <Demo recording={recording} />
        ) : (
          <p className="load-state" role="status">
            Loading the verified recording…
          </p>
        )}
      </main>
      <footer>
        <span>RepoScope / an engineering portfolio project</span>
        <a
          href={`${PROJECT}/blob/main/docs/interactive-demo.md`}
          target="_blank"
          rel="noreferrer"
        >
          How this demo works ↗
        </a>
      </footer>
    </>
  );
}
