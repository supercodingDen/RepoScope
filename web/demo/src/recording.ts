import { z } from "zod";

export const SOURCE_COMMIT = "672971d66a2ef9f85151e53283113f33d642dabd";
export const PROJECT = "https://github.com/supercodingDen/RepoScope";
const path = z
  .string()
  .min(1)
  .max(512)
  .refine(
    (value) =>
      !value.startsWith("/") &&
      !value.includes("\\") &&
      !value.includes(":") &&
      value
        .split("/")
        .every((part) => part !== ".." && part !== "." && part !== ""),
  );
const citationFields = {
  chunk_id: z.uuid(),
  repository_id: z.uuid(),
  generation_id: z.uuid(),
  commit_sha: z.literal(SOURCE_COMMIT),
  path,
  start_line: z.number().int().positive(),
  end_line: z.number().int().positive(),
};
const citation = z.strictObject(citationFields);
const match = z
  .strictObject({
    ...citationFields,
    score: z.number().finite().nonnegative(),
    content: z.string().min(1).max(12000),
  })
  .refine(
    (item) =>
      item.end_line >= item.start_line &&
      item.end_line - item.start_line + 1 ===
        item.content.replace(/\n$/, "").split("\n").length,
  );
const result = z.strictObject({
  answer: z.string().min(1).max(16000),
  citations: z.array(citation).max(20),
  evidence_status: z.enum(["supported", "insufficient"]),
  model: z.literal("mock"),
  estimated_cost_usd: z.literal("0.000000"),
});
const event = z.strictObject({
  run_id: z.uuid(),
  sequence: z.number().int().positive(),
  occurred_at: z.iso.datetime({ offset: true }),
  data: z.discriminatedUnion("kind", [
    z.strictObject({
      kind: z.literal("run.started"),
      model: z.literal("mock"),
    }),
    z.strictObject({
      kind: z.enum(["tool.started", "tool.completed"]),
      tool: z.enum(["search_code", "get_file", "get_repository_summary"]),
      step: z.number().int().min(1).max(6),
    }),
    z.strictObject({ kind: z.literal("run.completed"), result }),
  ]),
});
const demoCase = z
  .strictObject({
    id: z.enum(["lookup", "scoped", "resume"]),
    title: z.string().min(1).max(100),
    question: z.string().min(1).max(200),
    path_prefix: path.nullable(),
    search: z.strictObject({
      repository_id: z.uuid(),
      generation_id: z.uuid(),
      commit_sha: z.literal(SOURCE_COMMIT),
      results: z.array(match).min(1).max(20),
      duration_ms: z.number().finite().nonnegative(),
    }),
    result,
    events: z.array(event).min(2).max(32),
    resume_after: z.number().int().positive().nullable(),
    resumed_sequences: z.array(z.number().int().positive()),
  })
  .refine((item) => {
    if (
      new Set(item.search.results.map((m) => m.chunk_id)).size !==
      item.search.results.length
    )
      return false;
    if ((item.id === "scoped") !== (item.path_prefix !== null)) return false;
    if ((item.id === "resume") !== (item.resume_after === 2)) return false;
    const first = item.events[0];
    const last = item.events.at(-1);
    if (
      !first ||
      first.data.kind !== "run.started" ||
      !last ||
      last.data.kind !== "run.completed"
    )
      return false;
    if (JSON.stringify(last.data.result) !== JSON.stringify(item.result))
      return false;
    if (
      item.result.evidence_status === "supported" &&
      item.result.citations.length === 0
    )
      return false;
    if (
      !item.events.every(
        (e, i) =>
          e.sequence === i + 1 &&
          e.run_id === first.run_id &&
          (i === 0 ||
            (e.data.kind !== "run.started" &&
              Date.parse(e.occurred_at) >=
                Date.parse(item.events[i - 1]?.occurred_at ?? ""))) &&
          (i === item.events.length - 1 || e.data.kind !== "run.completed"),
      )
    )
      return false;
    if (
      !item.search.results.every(
        (m) =>
          m.repository_id === item.search.repository_id &&
          m.generation_id === item.search.generation_id &&
          (!item.path_prefix ||
            m.path === item.path_prefix ||
            m.path.startsWith(item.path_prefix + "/")),
      )
    )
      return false;
    if (
      !item.result.citations.every((c) =>
        item.search.results.some(
          (m) =>
            m.chunk_id === c.chunk_id &&
            m.repository_id === c.repository_id &&
            m.generation_id === c.generation_id &&
            m.path === c.path &&
            m.start_line === c.start_line &&
            m.end_line === c.end_line,
        ),
      )
    )
      return false;
    const resumed =
      item.resume_after === null
        ? []
        : item.events
            .filter((e) => e.sequence > item.resume_after!)
            .map((e) => e.sequence);
    return (
      (item.resume_after === null || item.resume_after < item.events.length) &&
      JSON.stringify(resumed) === JSON.stringify(item.resumed_sequences)
    );
  });

export const recordingSchema = z
  .strictObject({
    schema_version: z.literal(1),
    recorded_at: z.iso.datetime({ offset: true }),
    application_commit: z.string().regex(/^[a-f0-9]{40}$/),
    repository_url: z.literal("https://github.com/pallets/itsdangerous"),
    commit_sha: z.literal(SOURCE_COMMIT),
    provider_mode: z.literal("mock"),
    cases: z.array(demoCase).length(3),
  })
  .refine(
    (value) =>
      new Set(value.cases.map((c) => c.id)).size === value.cases.length,
  );

export type Recording = z.infer<typeof recordingSchema>;
export type DemoCase = z.infer<typeof demoCase>;
export type Match = z.infer<typeof match>;
export type RunEvent = z.infer<typeof event>;

export function sourceLink(item: Match): string {
  return `https://github.com/pallets/itsdangerous/blob/${SOURCE_COMMIT}/${item.path.split("/").map(encodeURIComponent).join("/")}#L${item.start_line}-L${item.end_line}`;
}

export const manifestSchema = z.strictObject({
  commit_sha: z.literal(SOURCE_COMMIT),
  excerpts: z.record(z.string(), z.string().regex(/^[a-f0-9]{64}$/)),
});

export async function excerptDigest(content: string): Promise<string> {
  const bytes = new TextEncoder().encode(content.replace(/\n$/, ""));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}

async function loadJson(path: string): Promise<unknown> {
  const response = await fetch(path);
  if (!response.ok) throw new Error("Recording unavailable");
  const text = await response.text();
  if (text.length > 500000) throw new Error("Recording too large");
  const value: unknown = JSON.parse(text);
  return value;
}

export async function loadRecording(): Promise<Recording> {
  const [raw, approved] = await Promise.all([
    loadJson("./recordings/demo.json"),
    loadJson("./recordings/approved-excerpts.json"),
  ]);
  const recording = recordingSchema.parse(raw);
  const manifest = manifestSchema.parse(approved);
  for (const item of recording.cases) {
    for (const match of item.search.results) {
      const key = `${match.path}:${match.start_line}:${match.end_line}`;
      if (manifest.excerpts[key] !== (await excerptDigest(match.content)))
        throw new Error("Unverified excerpt");
    }
    const cited = item.search.results.find(
      (m) => m.chunk_id === item.result.citations[0]?.chunk_id,
    );
    if (
      !cited ||
      item.result.citations.length !== 1 ||
      item.result.answer !==
        `Relevant source: ${cited.path}:${cited.start_line}-${cited.end_line}. ${cited.content.slice(0, 1000)}`
    ) {
      throw new Error("Unverified mock result");
    }
  }
  return recording;
}
