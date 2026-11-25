import { workspaceMarkup } from "./views.js";
import type {
  Bootstrap,
  ChatMessage,
  Filters,
  Language,
  Memory,
  Review,
  Session,
  TrashEntry,
  View,
} from "./types.js";
import {
  filterSessions,
  isInteractive,
  persist,
  readPreference,
  readReview,
  stale,
  visibleSelection,
  commandFor,
} from "./state.js";
import { translate, type TextKey } from "./i18n.js";

const root = document.querySelector<HTMLDivElement>("#app")!;
let bootstrap: Bootstrap;
try {
  const parsed = JSON.parse(
    document.querySelector("#app-data")?.textContent ?? "{}",
  ) as Bootstrap;
  if (
    !Array.isArray(parsed.sessions) ||
    !Array.isArray(parsed.memories) ||
    !Array.isArray(parsed.trash) ||
    !["demo", "local", "static"].includes(parsed.mode)
  )
    throw new Error("Invalid workspace");
  bootstrap = parsed;
} catch {
  root.textContent =
    "The workspace could not be loaded. / No se pudo cargar el espacio.";
  throw new Error("Invalid Session Desk bootstrap");
}
const original = structuredClone(bootstrap);
let catalog = structuredClone(bootstrap);
const safeStorage = {
  getItem: (key: string): string | null => {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
};
let language: Language = readPreference(
  safeStorage,
  "language",
  ["en", "es"],
  navigator.language.startsWith("es") ? "es" : "en",
);
let theme = readPreference(
  safeStorage,
  "theme",
  ["light", "dark"],
  matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light",
);
let reviews: Record<string, Review> = readReview(safeStorage);
let view: View = "sessions";
let filters: Filters = {
  query: "",
  provider: "all",
  project: "",
  review: "all",
  sort: "updated",
  ascending: false,
};
let age = "all";
let selected = new Set<string>();
let detailId = catalog.sessions[0]?.id ?? "";
let detailTab = "conversation";
let mobileDetail = false;
let busy = false;
let notice = "";
let error = "";
let copied = false;
let conversations: Record<string, ChatMessage[]> = {};
let loadingConversation = "";
const demoRemoved = new Map<string, Session | Memory>();
const t = (key: TextKey): string => translate(language, key);
const referenceTime = (): number =>
  Math.max(
    Date.parse(catalog.generated_at) / 1000 || 0,
    ...catalog.memories.map((item) => item.timestamp),
  );
const isStale = (memory: Memory): boolean => stale(memory, referenceTime());
function visibleItems(): (Session | Memory | TrashEntry)[] {
  if (view === "sessions")
    return filterSessions(catalog.sessions, filters, reviews);
  const query = filters.query.toLocaleLowerCase().trim();
  if (view === "trash")
    return catalog.trash
      .filter((item) =>
        `${item.title} ${item.project_path}`
          .toLocaleLowerCase()
          .includes(query),
      )
      .sort((a, b) => b.deleted_at.localeCompare(a.deleted_at));
  return catalog.memories
    .filter(
      (item) =>
        (filters.provider === "all" || item.provider === filters.provider) &&
        (!filters.project || item.project_path === filters.project) &&
        (age === "all" || (age === "stale") === isStale(item)) &&
        `${item.name} ${item.description} ${item.body} ${item.project_path}`
          .toLocaleLowerCase()
          .includes(query),
    )
    .sort(
      (a, b) =>
        (filters.sort === "title"
          ? a.name.localeCompare(b.name)
          : a.timestamp - b.timestamp) * (filters.ascending ? 1 : -1),
    );
}
function render(): void {
  const active = document.activeElement as HTMLInputElement | null;
  const focusId = active?.id;
  const focusTest = active?.dataset.testid;
  const focusAction = active?.dataset.action;
  const focusOpen = active?.dataset.open;
  const focusSelect = active?.dataset.select;
  const selectionStart =
    active?.tagName === "INPUT" && active.type === "search"
      ? active.selectionStart
      : null;
  const listScroll = root.querySelector(".list-scroll")?.scrollTop ?? 0;
  const detailScroll = root.querySelector(".detail-content")?.scrollTop ?? 0;
  const items = visibleItems();
  selected = visibleSelection(selected, items);
  if (detailId && !items.some((item) => item.id === detailId)) {
    detailId = "";
    mobileDetail = false;
  }
  document.documentElement.lang = language;
  document.documentElement.dataset.theme = theme;
  root.innerHTML = workspaceMarkup({
    catalog,
    language,
    theme,
    reviews,
    view,
    filters,
    age,
    selected,
    detailId,
    detailTab,
    mobileDetail,
    busy,
    notice,
    error,
    copied,
    conversations,
    loadingConversation,
    items,
  });
  const all = root.querySelector<HTMLInputElement>("#select-all");
  if (all)
    all.indeterminate = selected.size > 0 && selected.size < items.length;
  const focusTarget = focusId
    ? document.getElementById(focusId)
    : focusOpen
      ? root.querySelector<HTMLElement>(
          `[data-open="${CSS.escape(focusOpen)}"]`,
        )
      : focusSelect
        ? root.querySelector<HTMLElement>(
            `[data-select="${CSS.escape(focusSelect)}"]`,
          )
        : focusAction
          ? root.querySelector<HTMLElement>(
              `[data-action="${CSS.escape(focusAction)}"]`,
            )
          : focusTest
            ? root.querySelector<HTMLElement>(
                `[data-testid="${CSS.escape(focusTest)}"]`,
              )
            : null;
  focusTarget?.focus({ preventScroll: true });
  if (selectionStart !== null && focusTarget instanceof HTMLInputElement)
    focusTarget.setSelectionRange(selectionStart, selectionStart);
  const listElement = root.querySelector(".list-scroll");
  if (listElement) listElement.scrollTop = listScroll;
  const detailElement = root.querySelector(".detail-content");
  if (detailElement) detailElement.scrollTop = detailScroll;
}
function clearFilters(): void {
  filters = {
    ...filters,
    query: "",
    provider: "all",
    project: "",
    review: "all",
  };
  age = "all";
  selected.clear();
}
function openItem(id: string): void {
  detailId = id;
  mobileDetail = true;
  copied = false;
  detailTab = "conversation";
  render();
  root.querySelector(".detail-content")?.scrollTo(0, 0);
  void loadConversation(id);
}
async function loadConversation(id: string): Promise<void> {
  if (
    catalog.mode !== "local" ||
    id in conversations ||
    !catalog.sessions.some((session) => session.id === id)
  )
    return;
  loadingConversation = id;
  render();
  try {
    const result = (await api(
      `/api/sessions/${encodeURIComponent(id)}/messages`,
    )) as { messages?: ChatMessage[] };
    if (Array.isArray(result.messages)) conversations[id] = result.messages;
  } catch {
    // The preview from the catalog stays visible if the full text can't be read.
  }
  if (loadingConversation === id) loadingConversation = "";
  render();
}
async function api(path: string, body?: unknown): Promise<unknown> {
  if (catalog.mode !== "local") throw new Error(t("readOnly"));
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: {
      "X-Panel-Token": catalog.token ?? "",
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const result = (await response.json()) as { error?: string };
  if (!response.ok)
    throw new Error(
      typeof result.error === "string" ? result.error : t("requestFailed"),
    );
  return result;
}
async function refresh(): Promise<void> {
  const value = (await api("/api/catalog")) as Bootstrap;
  if (
    !Array.isArray(value.sessions) ||
    !Array.isArray(value.memories) ||
    !Array.isArray(value.trash)
  )
    throw new Error(t("requestFailed"));
  catalog = value;
  conversations = {};
  if (detailId) void loadConversation(detailId);
}
async function mutate(kind: "trash" | "restore", ids: string[]): Promise<void> {
  if (busy || catalog.mode === "static" || !ids.length) return;
  busy = true;
  error = "";
  notice = "";
  render();
  try {
    if (catalog.mode === "demo") {
      if (kind === "trash") {
        const entries =
          view === "sessions" ? catalog.sessions : catalog.memories;
        for (const item of entries.filter((entry) => ids.includes(entry.id))) {
          demoRemoved.set(item.id, item);
          catalog.trash.unshift({
            id: item.id,
            kind: view === "sessions" ? "session" : "memory",
            provider: item.provider,
            title: "title" in item ? item.title : item.name,
            project_path: item.project_path,
            deleted_at: new Date().toISOString(),
            size_bytes: item.size_bytes,
          });
        }
        catalog.sessions = catalog.sessions.filter(
          (item) => !ids.includes(item.id),
        );
        catalog.memories = catalog.memories.filter(
          (item) => !ids.includes(item.id),
        );
      } else {
        for (const id of ids) {
          const item = demoRemoved.get(id);
          if (!item) {
            error = t("requestFailed");
            continue;
          }
          if ("session_id" in item) catalog.sessions.push(item);
          else catalog.memories.push(item);
          catalog.trash = catalog.trash.filter((entry) => entry.id !== id);
          demoRemoved.delete(id);
        }
      }
    } else {
      const versions = Object.fromEntries(
        [...catalog.sessions, ...catalog.memories]
          .filter((item) => ids.includes(item.id))
          .map((item) => [item.id, item.version]),
      );
      const result = (await api(
        `/api/${kind}`,
        kind === "trash"
          ? { ids, versions, kind: view === "sessions" ? "session" : "memory" }
          : { ids },
      )) as { done: string[]; errors: { message: string }[] };
      await refresh();
      if (result.errors?.length)
        error = result.errors.map((item) => item.message).join(" ");
    }
    selected.clear();
    if (!error) notice = t(kind === "trash" ? "moved" : "restored");
  } catch (failure) {
    error = failure instanceof Error ? failure.message : t("requestFailed");
  } finally {
    busy = false;
    render();
  }
}
root.addEventListener("input", (event) => {
  const input = event.target as HTMLInputElement;
  if (input.id === "search") {
    filters.query = input.value;
    render();
  }
});
root.addEventListener("change", (event) => {
  const control = event.target as HTMLInputElement | HTMLSelectElement;
  if (control.dataset.select) {
    if ((control as HTMLInputElement).checked)
      selected.add(control.dataset.select);
    else selected.delete(control.dataset.select);
  } else if (control.id === "select-all")
    selected = (control as HTMLInputElement).checked
      ? new Set(visibleItems().map((item) => item.id))
      : new Set();
  else if (control.id === "language") {
    language = control.value as Language;
    persist("language", language);
  } else if (control.id === "provider") filters.provider = control.value;
  else if (control.id === "project") filters.project = control.value;
  else if (control.id === "review") filters.review = control.value;
  else if (control.id === "age") age = control.value;
  render();
});
root.addEventListener("click", async (event) => {
  const target = (event.target as HTMLElement).closest<HTMLElement>(
    "[data-action], [data-open], [data-memory]",
  );
  if (!target) return;
  if (target instanceof HTMLButtonElement && target.disabled) return;
  if (target.dataset.open) {
    openItem(target.dataset.open);
    return;
  }
  if (target.dataset.memory) {
    detailId = target.dataset.memory;
    clearFilters();
    openItem(detailId);
    return;
  }
  const action = target.dataset.action ?? "";
  if (action === "home" || action.startsWith("view-")) {
    event.preventDefault();
    view = action === "home" ? "sessions" : (action.slice(5) as View);
    clearFilters();
    detailId = "";
    mobileDetail = false;
    notice = "";
    error = "";
    render();
    return;
  }
  if (action === "theme") {
    theme = theme === "light" ? "dark" : "light";
    persist("theme", theme);
  } else if (action === "reset") {
    catalog = structuredClone(original);
    demoRemoved.clear();
    reviews = {};
    clearFilters();
    detailId = catalog.sessions[0]?.id ?? "";
    view = "sessions";
    mobileDetail = false;
    notice = t("resetDone");
    error = "";
  } else if (action === "clear-filters") clearFilters();
  else if (action === "clear-selection") selected.clear();
  else if (action === "dismiss-error") error = "";
  else if (action === "dismiss-notice") notice = "";
  else if (action === "close-detail") {
    detailId = "";
    mobileDetail = false;
  } else if (action.startsWith("sort-")) {
    const next = action.slice(5) as Filters["sort"];
    filters.ascending =
      filters.sort === next ? !filters.ascending : next === "title";
    filters.sort = next;
  } else if (action.startsWith("tab-")) detailTab = action.slice(4);
  else if (action.startsWith("review-") && catalog.mode !== "static") {
    reviews[detailId] = action.slice(7) as Review;
    if (catalog.mode === "local") persist("review", reviews);
  } else if (action === "trash") {
    (document.getElementById("trash-dialog") as HTMLDialogElement).showModal();
    return;
  } else if (action === "confirm-trash") {
    (document.getElementById("trash-dialog") as HTMLDialogElement).close();
    await mutate("trash", [...visibleSelection(selected, visibleItems())]);
    root.querySelector<HTMLElement>("#search")?.focus();
    return;
  } else if (action === "restore") {
    await mutate("restore", [target.dataset.id ?? ""]);
    return;
  } else if (action === "origin") {
    view = "sessions";
    clearFilters();
    openItem(target.dataset.id ?? "");
    return;
  } else if (action === "copy") {
    const session = catalog.sessions.find((item) => item.id === detailId);
    if (session) {
      try {
        await navigator.clipboard.writeText(commandFor(session));
        copied = true;
      } catch {
        error = t("copyFailed");
      }
    }
  } else if (action === "refresh") {
    busy = true;
    render();
    try {
      await refresh();
      notice = t("refreshDone");
      error = "";
    } catch (failure) {
      error = failure instanceof Error ? failure.message : t("requestFailed");
    } finally {
      busy = false;
    }
  }
  render();
});
root.addEventListener("keydown", (event) => {
  const target = event.target as HTMLElement;
  if (
    target.getAttribute("role") === "tab" &&
    ["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
  ) {
    event.preventDefault();
    detailTab =
      event.key === "Home"
        ? "conversation"
        : event.key === "End"
          ? "details"
          : detailTab === "conversation"
            ? "details"
            : "conversation";
    render();
    document.getElementById(`tab-${detailTab}`)?.focus();
  }
});
document.addEventListener("keydown", (event) => {
  if (
    event.ctrlKey ||
    event.metaKey ||
    event.altKey ||
    isInteractive(event.target instanceof Element ? event.target : null)
  )
    return;
  if (event.key === "/") {
    event.preventDefault();
    document.getElementById("search")?.focus();
  } else if (event.key === "Escape" && detailId) {
    detailId = "";
    mobileDetail = false;
    render();
  } else if (["j", "k"].includes(event.key) && view !== "trash") {
    const items = visibleItems();
    if (!items.length) return;
    const index = items.findIndex((item) => item.id === detailId);
    const next = Math.max(
      0,
      Math.min(items.length - 1, index + (event.key === "j" ? 1 : -1)),
    );
    event.preventDefault();
    openItem(items[next].id);
    root
      .querySelector(`[data-open="${CSS.escape(items[next].id)}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }
});
render();
if (detailId) void loadConversation(detailId);
