import { test, expect } from "@playwright/test";
import {
  recordingSchema,
  manifestSchema,
  excerptDigest,
} from "../src/recording";

test("recording exposes pinned evidence and resets playback when changing case", async ({
  page,
}) => {
  await page.goto("./");
  await expect(
    page.getByRole("heading", {
      name: "Understand the code. Verify the evidence.",
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Mock model + embeddings", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Play recording" }).click();
  await expect(
    page.getByRole("button", { name: "Pause playback" }),
  ).toBeVisible();
  await page.getByRole("button", { name: /02.*Focus the search/ }).click();
  await expect(
    page.getByRole("button", { name: "Play recording" }),
  ).toBeVisible();
  await expect(page.getByTestId("playback-progress")).toHaveText(
    "0 / 4 events",
  );
  await page.getByRole("button", { name: "View citation 1" }).click();
  await expect(
    page.getByRole("link", { name: "Open pinned source on GitHub" }),
  ).toHaveAttribute(
    "href",
    /github\.com\/pallets\/itsdangerous\/blob\/672971d66a2ef9f85151e53283113f33d642dabd\/.*#L\d+-L\d+/,
  );
});

test("resume proof and honest benchmark evidence remain inspectable", async ({
  page,
}) => {
  await page.goto("./");
  await page
    .getByRole("button", { name: /03.*Resume a disconnected stream/ })
    .click();
  await expect(page.getByText(/Last-Event-ID/).first()).toBeVisible();
  await page.getByRole("button", { name: "Next event" }).click();
  await expect(page.getByTestId("playback-progress")).toHaveText(
    "1 / 4 events",
  );
  await page.getByRole("tab", { name: "Evaluation" }).click();
  await expect(page.getByText("Target not met", { exact: true })).toBeVisible();
  await expect(page.getByText(/not semantic answer accuracy/)).toBeVisible();
  await page.getByRole("tab", { name: "Architecture" }).click();
  await expect(
    page.getByText("Transactional outbox", { exact: true }),
  ).toBeVisible();
});

test("untrusted data fails closed without exposing the supplied payload", async ({
  page,
}) => {
  await page.route("**/recordings/demo.json", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: '{"schema_version":1,"answer":"DO_NOT_ECHO_PRIVATE_DATA"}',
    }),
  );
  await page.goto("./");
  await expect(page.getByRole("alert")).toContainText("Recording unavailable");
  await expect(page.getByText("DO_NOT_ECHO_PRIVATE_DATA")).toHaveCount(0);
});

test("mobile layout fits the viewport and supports keyboard navigation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("./");
  await expect(
    page.getByRole("button", { name: "Play recording" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to demo" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#demo")).toBeFocused();
});

test("source excerpts render as inert text and foreign event sequences are rejected", async ({
  page,
}) => {
  const value = recordingSchema.parse(
    await (await page.request.get("./recordings/demo.json")).json(),
  );
  const manifest = manifestSchema.parse(
    await (
      await page.request.get("./recordings/approved-excerpts.json")
    ).json(),
  );
  const first = value.cases[0]?.search.results[0];
  const result = value.cases[0]?.result;
  const terminal = value.cases[0]?.events.at(-1)?.data;
  if (!first || !result || terminal?.kind !== "run.completed")
    throw new Error("Missing evidence fixture");
  first.content = first.content.replace(
    /^[^\n]*/,
    "<img src=x onerror=\"document.title='UNSAFE'\">",
  );
  for (const entry of value.cases) {
    for (const match of entry.search.results) {
      if (
        match.path === first.path &&
        match.start_line === first.start_line &&
        match.end_line === first.end_line
      )
        match.content = first.content;
    }
    const cited = entry.search.results.find(
      (m) => m.chunk_id === entry.result.citations[0]?.chunk_id,
    );
    const completed = entry.events.at(-1)?.data;
    if (cited && completed?.kind === "run.completed") {
      entry.result.answer = `Relevant source: ${cited.path}:${cited.start_line}-${cited.end_line}. ${cited.content.slice(0, 1000)}`;
      completed.result = entry.result;
    }
  }
  result.answer = `Relevant source: ${first.path}:${first.start_line}-${first.end_line}. ${first.content.slice(0, 1000)}`;
  terminal.result = result;
  manifest.excerpts[`${first.path}:${first.start_line}:${first.end_line}`] =
    await excerptDigest(first.content);
  await page.route("**/recordings/demo.json", (route) =>
    route.fulfill({ json: value }),
  );
  await page.route("**/recordings/approved-excerpts.json", (route) =>
    route.fulfill({ json: manifest }),
  );
  await page.goto("./");
  await expect(page.getByLabel("Recorded source excerpt")).toContainText(
    "<img src=x",
  );
  await expect(page).toHaveTitle(
    "RepoScope — Evidence-backed Code Intelligence",
  );
  await page.unroute("**/recordings/demo.json");
  await page.unroute("**/recordings/approved-excerpts.json");
  await page.route("**/recordings/demo.json", async (route) => {
    const response = await route.fetch();
    const value = recordingSchema.parse(await response.json());
    const event = value.cases[0]?.events[1];
    if (!event) throw new Error("Missing event fixture");
    event.sequence = 10;
    await route.fulfill({ json: value });
  });
  await page.reload();
  await expect(page.getByRole("alert")).toContainText("Recording unavailable");
});

test("tabs switch by arrow keys and disclose the separate scoped search", async ({
  page,
}) => {
  await page.goto("./");
  await page.getByRole("tab", { name: "Workbench" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Architecture" })).toBeFocused();
  await expect(page.getByRole("tabpanel")).toContainText(
    "Transactional outbox",
  );
  await page.keyboard.press("Home");
  await page.getByRole("button", { name: /02.*Focus the search/ }).click();
  await expect(
    page.getByText(
      "Scope applies only to the recorded search below. Agent output and tool events come from an unfiltered run.",
    ),
  ).toBeVisible();
});
