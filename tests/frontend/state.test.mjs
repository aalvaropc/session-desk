import test from "node:test";
import assert from "node:assert/strict";
import {
  readReview,
  readPreference,
  filterSessions,
  visibleSelection,
  isInteractive,
  wikiParts,
} from "../.compiled/state.mjs";
const storage = (value) => ({ getItem: () => value });
test("corrupt and structurally invalid review storage resets safely", () => {
  for (const value of ["{bad", "null", "[]", '"value"'])
    assert.deepEqual(readReview(storage(value)), {});
  assert.deepEqual(
    readReview(storage('{"one":"keep","two":"pending","three":true}')),
    { one: "keep", two: "pending" },
  );
});
test("invalid preferences fall back to the supplied supported default", () => {
  assert.equal(
    readPreference(storage('"fr"'), "language", ["en", "es"], "es"),
    "es",
  );
  assert.equal(
    readPreference(storage('"en"'), "language", ["en", "es"], "es"),
    "en",
  );
});
test("search and filters compose across title, conversation and project", () => {
  const sessions = [
    {
      id: "1",
      provider: "claude",
      title: "Checkout",
      first_message: "",
      project_path: "/work/store",
      messages: [{ text: "race condition" }],
      timestamp: 3,
    },
    {
      id: "2",
      provider: "codex",
      title: "Checkout",
      first_message: "",
      project_path: "/work/docs",
      messages: [],
      timestamp: 4,
    },
  ];
  assert.deepEqual(
    filterSessions(
      sessions,
      {
        query: "race",
        provider: "claude",
        project: "",
        review: "all",
        sort: "updated",
        ascending: false,
      },
      { 1: "keep" },
    ).map((s) => s.id),
    ["1"],
  );
  assert.equal(
    filterSessions(
      sessions,
      {
        query: "",
        provider: "all",
        project: "",
        review: "pending",
        sort: "updated",
        ascending: false,
      },
      { 1: "keep" },
    ).length,
    1,
  );
});
test("filter changes remove invisible selections before bulk actions", () => {
  assert.deepEqual(
    [...visibleSelection(new Set(["1", "2"]), [{ id: "2" }])],
    ["2"],
  );
});
test("keyboard shortcut guards include native and contenteditable controls", () => {
  for (const selector of [
    "INPUT",
    "BUTTON",
    "SELECT",
    "TEXTAREA",
    "A",
    "SUMMARY",
  ])
    assert.equal(
      isInteractive({
        closest: (query) =>
          query.includes(selector.toLowerCase()) ? {} : null,
      }),
      true,
    );
});
test("wikilinks preserve readable aliases and filenames for lookup", () => {
  assert.deepEqual(
    wikiParts("Read [[architecture|the plan]] and [[missing.md]]."),
    [
      { text: "Read " },
      { text: "the plan", target: "architecture" },
      { text: " and " },
      { text: "missing.md", target: "missing.md" },
      { text: "." },
    ],
  );
});
test("memory links resolve inside their project even when filenames repeat", async () => {
  const { resolveMemoryLink } = await import("../.compiled/state.mjs");
  const memories = [
    {
      id: "one",
      name: "Guidelines",
      file_path: "/a/guidelines.md",
      project_path: "/a",
    },
    {
      id: "two",
      name: "Guidelines",
      file_path: "/b/guidelines.md",
      project_path: "/b",
    },
  ];
  assert.equal(resolveMemoryLink(memories, "guidelines.md", "/b")?.id, "two");
  assert.equal(
    resolveMemoryLink(memories, "guidelines", "/missing"),
    undefined,
  );
});
test("memory origins use the same provider and project when native IDs repeat", async () => {
  const { resolveOriginSession } = await import("../.compiled/state.mjs");
  const memory = {
    origin_session_id: "native",
    provider: "claude",
    project_path: "/correct",
  };
  const sessions = [
    {
      id: "wrong-project",
      session_id: "native",
      provider: "claude",
      project_path: "/other",
    },
    {
      id: "wrong-provider",
      session_id: "native",
      provider: "codex",
      project_path: "/correct",
    },
    {
      id: "correct",
      session_id: "native",
      provider: "claude",
      project_path: "/correct",
    },
  ];
  assert.equal(resolveOriginSession(sessions, memory)?.id, "correct");
  assert.equal(
    resolveOriginSession(sessions, { ...memory, project_path: "/missing" }),
    undefined,
  );
});
