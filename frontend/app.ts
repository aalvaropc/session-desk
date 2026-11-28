import { workspaceMarkup } from "./views.js";
import type {
  Bootstrap,
  ActivityGroup,
  ConversationPage,
  ConversationState,
  Filters,
  IndexProgress,
  Language,
  Memory,
  Note,
  NoteDraft,
  Review,
  Session,
  SessionPage,
  SessionTab,
  TrashEntry,
  View,
} from "./types.js";
import { sessionTabs } from "./types.js";
import {
  filterSessions,
  isInteractive,
  persist,
  projectContains,
  readPreference,
  readReview,
  stale,
  visibleSelection,
  commandFor,
} from "./state.js";
import { translate, type TextKey } from "./i18n.js";
import {
  contextMarkdown,
  embeddedConversation,
  localActivity,
  noteMarkdown,
} from "./analysis.js";

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
let detailTab: SessionTab = "conversation";
let readingMode = false;
let listScroll = 0;
let mobileDetail = false;
let busy = false;
let notice = "";
let error = "";
let copied = false;
let copiedMessage: number | undefined;
let sessionPage: SessionPage | undefined;
let pageOffset = 0;
let listPending = !!catalog.paged;
let indexProgress: IndexProgress = { phase: "idle" };
let indexMonitor = 0;
let openInitialSession = true;
let listRequest = 0;
let searchTimer: number | undefined;
let activeSession: Session | undefined;
let conversation: ConversationState | undefined;
let targetMessage: number | undefined;
let sessionRequest = 0;
let activity: ActivityGroup[] = [];
let activityDays = 7;
let activityRequest = 0;
let noteDraft: NoteDraft | undefined;
const conversationCache = new Map<string, ConversationPage>();
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
    return catalog.paged
      ? catalog.sessions
      : filterSessions(catalog.sessions, filters, reviews);
  const query = filters.query.toLocaleLowerCase().trim();
  if (view === "activity") return [];
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
        (!filters.project ||
          projectContains(filters.project, item.project_path)) &&
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
  if (noteDraft && root.querySelector<HTMLDialogElement>("#note-dialog")?.open)
    return;
  const active = document.activeElement as HTMLInputElement | null;
  const focusId = active?.id;
  const focusTest = active?.dataset.testid;
  const focusAction = active?.dataset.action;
  const focusPosition = active?.dataset.position;
  const focusOpen = active?.dataset.open;
  const focusSelect = active?.dataset.select;
  const selectionStart =
    active?.tagName === "INPUT" && active.type === "search"
      ? active.selectionStart
      : null;
  const previousList = root.querySelector(".list-scroll");
  if (previousList?.getClientRects().length)
    listScroll = previousList.scrollTop;
  const previousDetail = root.querySelector(".detail-content");
  const detailScroll =
    previousDetail?.getAttribute("aria-labelledby") === `tab-${detailTab}` ||
    view === "memories"
      ? (previousDetail?.scrollTop ?? 0)
      : 0;
  const items = visibleItems();
  selected = visibleSelection(selected, items);
  if (
    detailId &&
    activeSession?.id !== detailId &&
    !items.some((item) => item.id === detailId)
  ) {
    detailId = "";
    readingMode = false;
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
    readingMode,
    mobileDetail,
    busy,
    notice,
    error,
    copied,
    copiedMessage,
    activeSession,
    conversation,
    targetMessage,
    sessionPage,
    pageOffset,
    listPending,
    indexProgress,
    activity,
    activityDays,
    noteDraft,
    items,
  });
  const all = root.querySelector<HTMLInputElement>("#select-all");
  if (all)
    all.indeterminate =
      selected.size > 0 && selected.size < selectableItems().length;
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
              `[data-action="${CSS.escape(focusAction)}"]${focusPosition === undefined ? "" : `[data-position="${CSS.escape(focusPosition)}"]`}`,
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
function selectableItems(): (Session | Memory | TrashEntry)[] {
  return visibleItems().filter((item) => item.provider !== "antigravity");
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
function closeDetail(): void {
  sessionRequest++;
  activeSession = undefined;
  conversation = undefined;
  targetMessage = undefined;
  detailId = "";
  readingMode = false;
  mobileDetail = false;
}
function openItem(id: string, position?: number): void {
  const request = ++sessionRequest;
  detailId = id;
  mobileDetail = true;
  copied = false;
  copiedMessage = undefined;
  detailTab = "conversation";
  activeSession =
    view === "sessions"
      ? catalog.sessions.find((item) => item.id === id)
      : undefined;
  conversation = undefined;
  targetMessage = position ?? activeSession?.hit?.position;
  render();
  root.querySelector(".detail-content")?.scrollTo(0, 0);
  if (view !== "sessions") return;
  if (activeSession) {
    void loadConversation();
  } else if (catalog.paged) {
    void api(`/api/sessions/${encodeURIComponent(id)}`)
      .then((result) => {
        if (request !== sessionRequest) return;
        detailId = id;
        activeSession = result as Session;
        mobileDetail = true;
        if (activeSession.review) reviews[id] = activeSession.review;
        void loadConversation();
      })
      .catch((failure: unknown) => {
        if (request === sessionRequest) showError(failure);
      });
  }
}
function scrollToMessage(): void {
  if (targetMessage === undefined) return;
  const message = root.querySelector<HTMLElement>(
    `[data-position="${targetMessage}"]`,
  );
  message?.scrollIntoView({ block: "nearest" });
  if (message && document.activeElement?.closest(".detail-panel"))
    message.focus({ preventScroll: true });
}
function cacheConversation(key: string, page: ConversationPage): void {
  if (conversationCache.size >= 12) {
    const oldest = conversationCache.keys().next().value;
    if (oldest) conversationCache.delete(oldest);
  }
  conversationCache.set(key, page);
}
async function loadConversation(
  offset = Math.floor((targetMessage ?? 0) / 40) * 40,
): Promise<void> {
  const session = activeSession;
  if (!session) return;
  const current: ConversationState = {
    id: session.id,
    version: session.version,
    offset,
    loading: false,
    failed: false,
  };
  conversation = current;
  if (!catalog.paged || session.has_transcript === false) {
    current.page = embeddedConversation(session);
    render();
    scrollToMessage();
    return;
  }
  const key = `${session.id}/${session.version}/${offset}`;
  current.page = conversationCache.get(key);
  if (current.page) {
    render();
    scrollToMessage();
    return;
  }
  current.loading = true;
  render();
  try {
    const params = new URLSearchParams({
      offset: String(offset),
      version: session.version,
    });
    const result = (await api(
      `/api/sessions/${encodeURIComponent(session.id)}/messages?${params}`,
    )) as ConversationPage;
    if (conversation !== current) return;
    current.page = result;
    cacheConversation(key, result);
  } catch {
    current.failed = true;
  } finally {
    if (conversation === current) {
      current.loading = false;
      render();
      scrollToMessage();
    }
  }
}
function showError(failure: unknown): void {
  error = failure instanceof Error ? failure.message : t("requestFailed");
  render();
}
async function fetchSessions({ reset = false } = {}): Promise<void> {
  if (!catalog.paged || view !== "sessions") return;
  const request = ++listRequest;
  listPending = true;
  if (reset) {
    pageOffset = 0;
    selected.clear();
  }
  const query = filters.query.trim();
  const params = new URLSearchParams({
    q: query,
    provider: filters.provider,
    project: filters.project,
    review: filters.review,
    sort: filters.sort,
    ascending: filters.ascending ? "1" : "0",
    offset: String(pageOffset),
  });
  render();
  try {
    const data = (await api(
      `/api/${query ? "search" : "sessions"}?${params}`,
    )) as SessionPage;
    if (request !== listRequest || view !== "sessions") return;
    if (pageOffset > 0 && data.sessions.length === 0) {
      pageOffset = Math.max(0, Math.floor((data.total - 1) / 50) * 50);
      await fetchSessions();
      return;
    }
    sessionPage = data;
    catalog.sessions = data.sessions;
    for (const session of data.sessions)
      reviews[session.id] = session.review ?? "pending";
  } catch (failure) {
    if (request === listRequest) showError(failure);
  } finally {
    if (request === listRequest) {
      listPending = false;
      render();
    }
  }
}
function scheduleSearch(): void {
  window.clearTimeout(searchTimer);
  if (!catalog.paged || view !== "sessions") return;
  listRequest++;
  listPending = true;
  closeDetail();
  selected.clear();
  searchTimer = window.setTimeout(
    () => void fetchSessions({ reset: true }),
    160,
  );
}
function updateSessionFilters(): void {
  if (!catalog.paged || view !== "sessions") return;
  window.clearTimeout(searchTimer);
  closeDetail();
  void fetchSessions({ reset: true });
}
async function refreshActivity(): Promise<void> {
  const request = ++activityRequest;
  try {
    const params = new URLSearchParams({
      days: String(activityDays),
      provider: filters.provider,
    });
    const result = catalog.paged
      ? ((await api(`/api/activity?${params}`)) as ActivityGroup[])
      : localActivity(
          catalog.sessions,
          referenceTime(),
          activityDays,
          filters.provider,
        );
    if (request === activityRequest && view === "activity") {
      activity = result;
      render();
    }
  } catch (failure) {
    if (request === activityRequest) showError(failure);
  }
}
function showNote(draft: NoteDraft): void {
  noteDraft = draft;
  render();
  root.querySelector<HTMLDialogElement>("#note-dialog")?.showModal();
}
function copyText(value: string): Promise<void> {
  return navigator.clipboard.writeText(value);
}
function exportNote(note: Note): void {
  const url = URL.createObjectURL(
    new Blob([noteMarkdown(note)], { type: "text/markdown;charset=UTF-8" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = `session-desk-note-${note.id}.md`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function saveNote(event: SubmitEvent): Promise<void> {
  const form = event.target;
  if (
    !(form instanceof HTMLFormElement) ||
    form.id !== "note-form" ||
    !noteDraft
  )
    return;
  event.preventDefault();
  const fields = new FormData(form);
  const draft = {
    ...noteDraft,
    title: String(fields.get("title")).trim(),
    body: String(fields.get("body")).trim(),
  };
  if (!draft.title || !draft.body) return;
  const submit = form.querySelector<HTMLButtonElement>('[type="submit"]');
  if (submit) submit.disabled = true;
  try {
    const saved =
      catalog.mode === "demo"
        ? {
            ...draft,
            id: draft.id ?? String(Date.now()),
            updated_at: Date.now() / 1000,
            source_available: true,
          }
        : ((await api("/api/notes", draft)) as Note);
    catalog.notes = [
      saved,
      ...(catalog.notes ?? []).filter((note) => note.id !== saved.id),
    ];
    noteDraft = undefined;
    notice = t("noteSaved");
    render();
  } catch {
    const message = form.querySelector<HTMLElement>("[role=alert]");
    if (message) message.textContent = t("requestFailed");
    if (submit) submit.disabled = false;
  }
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
async function refresh(cached = false): Promise<void> {
  const previous = activeSession?.id;
  const wasMobileDetail = mobileDetail;
  const previousTab = detailTab;
  const wasReading = readingMode;
  const previousMessage = targetMessage;
  const value = await refreshCatalog(cached);
  if (
    !Array.isArray(value.sessions) ||
    !Array.isArray(value.memories) ||
    !Array.isArray(value.trash)
  )
    throw new Error(t("requestFailed"));
  catalog = value;
  conversationCache.clear();
  closeDetail();
  if (view === "sessions") {
    await fetchSessions();
    const session = sessionPage?.sessions.find((row) => row.id === previous);
    if (session) {
      openItem(session.id, previousMessage);
      mobileDetail = wasMobileDetail;
      detailTab = previousTab;
      readingMode = wasReading;
      render();
    }
    openFirstSession();
  } else if (view === "activity") {
    await refreshActivity();
  }
  if (catalog.background_index) void monitorBackgroundIndex();
}
function openFirstSession(): void {
  const first = catalog.sessions[0];
  if (!openInitialSession || !first || view !== "sessions") return;
  openInitialSession = false;
  if (!detailId && !filters.query) {
    openItem(first.id);
    mobileDetail = false;
    render();
  }
}
async function monitorBackgroundIndex(): Promise<void> {
  const monitor = ++indexMonitor;
  const poll = async (): Promise<void> => {
    try {
      const state = (await api("/api/progress")) as IndexProgress;
      if (monitor !== indexMonitor) return;
      indexProgress = state;
      if ((state.revision ?? 0) > (catalog.index_revision ?? 0)) {
        await refresh(true);
        return;
      }
      if (state.phase === "idle") {
        const migrated = await migrateLegacyReviews();
        if (monitor !== indexMonitor) return;
        if (migrated) {
          await refresh(true);
          return;
        }
      }
      if (state.phase === "scan" || state.phase === "index") {
        window.setTimeout(() => {
          if (monitor === indexMonitor) void poll();
        }, 1500);
      }
      render();
    } catch (failure) {
      if (monitor !== indexMonitor) return;
      indexProgress = { phase: "idle" };
      showError(failure);
    }
  };
  await poll();
}
async function refreshCatalog(cached: boolean): Promise<Bootstrap> {
  const path = cached ? "/api/catalog?cached=1" : "/api/catalog";
  if (catalog.background_index) return (await api(path)) as Bootstrap;
  let active = true;
  let timer: number;
  const poll = async (): Promise<void> => {
    try {
      const progress = (await api("/api/progress")) as IndexProgress;
      if (active && progress.phase !== "idle") {
        indexProgress = progress;
        render();
      }
    } catch {
      // The catalog request reports its own errors.
    }
    if (active) timer = window.setTimeout(() => void poll(), 2000);
  };
  timer = window.setTimeout(() => void poll(), 700);
  try {
    return (await api(path)) as Bootstrap;
  } finally {
    active = false;
    window.clearTimeout(timer);
    indexProgress = { phase: "idle" };
  }
}
async function mutate(kind: "trash" | "restore", ids: string[]): Promise<void> {
  if (
    busy ||
    catalog.mode === "static" ||
    !ids.length ||
    (kind === "trash" && view === "sessions" && listPending)
  )
    return;
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
      await refresh(true);
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
    scheduleSearch();
    render();
  }
});
root.addEventListener("change", (event) => {
  const control = event.target as HTMLInputElement | HTMLSelectElement;
  if (control.closest("#note-form")) return;
  if (control.dataset.select) {
    if (listPending && view === "sessions") return;
    if ((control as HTMLInputElement).checked)
      selected.add(control.dataset.select);
    else selected.delete(control.dataset.select);
  } else if (control.id === "select-all")
    selected = (control as HTMLInputElement).checked
      ? new Set(selectableItems().map((item) => item.id))
      : new Set();
  else if (control.id === "language") {
    language = control.value as Language;
    persist("language", language);
  } else if (control.id === "provider") filters.provider = control.value;
  else if (control.id === "project") filters.project = control.value;
  else if (control.id === "review") filters.review = control.value;
  else if (control.id === "age") age = control.value;
  else if (control.id === "activity-days") activityDays = Number(control.value);
  if (["provider", "project", "review"].includes(control.id))
    updateSessionFilters();
  if (view === "activity" && ["provider", "activity-days"].includes(control.id))
    void refreshActivity();
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
    closeDetail();
    listRequest++;
    window.clearTimeout(searchTimer);
    if (view === "sessions") void fetchSessions({ reset: true });
    if (view === "activity") void refreshActivity();
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
    closeDetail();
    detailId = catalog.sessions[0]?.id ?? "";
    view = "sessions";
    mobileDetail = false;
    notice = t("resetDone");
    error = "";
  } else if (action === "clear-filters") {
    clearFilters();
    updateSessionFilters();
  } else if (action === "clear-selection") selected.clear();
  else if (action === "dismiss-error") error = "";
  else if (action === "dismiss-notice") notice = "";
  else if (action === "close-detail") {
    const previous = detailId;
    closeDetail();
    render();
    root
      .querySelector<HTMLElement>(`[data-open="${CSS.escape(previous)}"]`)
      ?.focus({ preventScroll: true });
    return;
  } else if (action === "reading-mode") {
    readingMode = !readingMode;
    if (readingMode) mobileDetail = true;
  } else if (action.startsWith("sort-")) {
    const next = action.slice(5) as Filters["sort"];
    filters.ascending =
      filters.sort === next ? !filters.ascending : next === "title";
    filters.sort = next;
    updateSessionFilters();
  } else if (action.startsWith("tab-"))
    detailTab = action.slice(4) as SessionTab;
  else if (action.startsWith("review-") && catalog.mode !== "static") {
    reviews[detailId] = action.slice(7) as Review;
    if (catalog.paged) {
      try {
        await api("/api/reviews", {
          reviews: { [detailId]: reviews[detailId] },
        });
        if (filters.review !== "all") await fetchSessions();
      } catch (failure) {
        showError(failure);
        await fetchSessions();
      }
    }
  } else if (action === "trash") {
    (document.getElementById("trash-dialog") as HTMLDialogElement).showModal();
    return;
  } else if (action === "confirm-trash") {
    (document.getElementById("trash-dialog") as HTMLDialogElement).close();
    await mutate("trash", [...visibleSelection(selected, selectableItems())]);
    root.querySelector<HTMLElement>("#search")?.focus();
    return;
  } else if (action === "restore") {
    await mutate("restore", [target.dataset.id ?? ""]);
    return;
  } else if (action === "origin" || action === "activity-session") {
    view = "sessions";
    clearFilters();
    void fetchSessions({ reset: true });
    openItem(
      target.dataset.id ?? "",
      target.dataset.position === undefined
        ? undefined
        : Number(target.dataset.position),
    );
    return;
  } else if (action === "page-next" || action === "page-previous") {
    closeDetail();
    selected.clear();
    pageOffset = Math.max(0, pageOffset + (action === "page-next" ? 50 : -50));
    await fetchSessions();
  } else if (action === "conversation-retry") {
    await loadConversation(conversation?.offset ?? 0);
  } else if (action === "conversation-page" || action === "context-message") {
    const sessionId = detailId;
    targetMessage =
      action === "context-message"
        ? Number(target.dataset.position)
        : undefined;
    detailTab = "conversation";
    await loadConversation(Number(target.dataset.offset));
    if (
      action === "context-message" &&
      detailId === sessionId &&
      detailTab === "conversation"
    ) {
      (
        root.querySelector<HTMLElement>(
          `article[data-position="${target.dataset.position}"]`,
        ) ?? document.getElementById("tab-conversation")
      )?.focus({ preventScroll: true });
    }
  } else if (action === "note-add") {
    const session =
      activeSession ?? catalog.sessions.find((item) => item.id === detailId);
    if (session) {
      const position = Number(target.dataset.position);
      const page = conversation?.page ?? embeddedConversation(session);
      showNote({
        session_id: session.id,
        version: session.version,
        position,
        title: "",
        body: page.messages[position - page.offset]?.text.slice(0, 50000) ?? "",
      });
    }
    return;
  } else if (action === "note-edit" || action === "note-export") {
    const note = catalog.notes?.find((item) => item.id === target.dataset.id);
    if (note) {
      if (action === "note-edit") showNote(note);
      else exportNote(note);
    }
    return;
  } else if (action === "cancel-note") {
    noteDraft = undefined;
    root.querySelector<HTMLDialogElement>("#note-dialog")?.close();
    render();
    return;
  } else if (
    action === "copy" ||
    action === "copy-context" ||
    action === "copy-message"
  ) {
    const session =
      activeSession ?? catalog.sessions.find((item) => item.id === detailId);
    if (session) {
      try {
        if (action === "copy-context") {
          const page = conversation?.page ?? embeddedConversation(session);
          await copyText(contextMarkdown(session, page.context, language));
          notice = t("contextCopied");
        } else if (action === "copy-message") {
          const position = Number(target.dataset.position);
          const page = conversation?.page ?? embeddedConversation(session);
          const message = page.messages[position - page.offset];
          if (message) {
            await copyText(message.text);
            if (detailId === session.id) copiedMessage = position;
          }
        } else {
          await copyText(
            commandFor(session) || session.title || session.session_id,
          );
          copied = true;
        }
      } catch {
        error = t(action === "copy" ? "copyFailed" : "clipboardError");
      }
    }
  } else if (action === "refresh") {
    busy = true;
    render();
    try {
      await refresh();
      if (!catalog.background_index) notice = t("refreshDone");
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
    const index = sessionTabs.indexOf(detailTab);
    const step = event.key === "ArrowLeft" ? -1 : 1;
    detailTab =
      event.key === "Home"
        ? "conversation"
        : event.key === "End"
          ? "details"
          : sessionTabs[
              (index + step + sessionTabs.length) % sessionTabs.length
            ];
    render();
    document.getElementById(`tab-${detailTab}`)?.focus();
  }
});
document.addEventListener("keydown", (event) => {
  if (
    event.key === "Escape" &&
    readingMode &&
    !event.defaultPrevented &&
    !root.querySelector("dialog[open]")
  ) {
    event.preventDefault();
    readingMode = false;
    render();
    root.querySelector<HTMLElement>('[data-action="reading-mode"]')?.focus();
    return;
  }
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
    closeDetail();
    render();
  } else if (
    ["j", "k"].includes(event.key) &&
    ["sessions", "memories"].includes(view)
  ) {
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
root.addEventListener("submit", (event) => void saveNote(event));
root.addEventListener(
  "cancel",
  (event) => {
    if (
      event.target instanceof HTMLDialogElement &&
      event.target.id === "note-dialog"
    )
      noteDraft = undefined;
  },
  true,
);
async function migrateLegacyReviews(): Promise<boolean> {
  const legacy = Object.entries(readReview(safeStorage)).filter(([id]) =>
    /^[a-z]+:[0-9a-f]{64}$/.test(id),
  );
  const migrationKey = `session-desk:review-migrated:v1:${catalog.workspace_id}`;
  if (!legacy.length || safeStorage.getItem(migrationKey)) return false;
  try {
    for (let offset = 0; offset < legacy.length; offset += 1000) {
      const batch = Object.fromEntries(legacy.slice(offset, offset + 1000));
      await api("/api/reviews", { reviews: batch, migrate: true });
    }
    localStorage.setItem(migrationKey, "true");
    return true;
  } catch {
    return false;
  }
}
async function initialize(): Promise<void> {
  render();
  if (!catalog.paged) {
    if (detailId) {
      activeSession = catalog.sessions[0];
      void loadConversation();
    }
    return;
  }
  try {
    await migrateLegacyReviews();
    await refresh(true);
  } catch (failure) {
    listPending = false;
    showError(failure);
  }
}
void initialize();
