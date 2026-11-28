import type {
  Bootstrap,
  ActivityGroup,
  ConversationState,
  Filters,
  IndexProgress,
  Language,
  Memory,
  NoteDraft,
  Review,
  Session,
  SessionPage,
  TrashEntry,
  View,
} from "./types.js";
import {
  basename,
  escapeHTML as esc,
  stale,
  wikiParts,
  resolveMemoryLink,
  resolveOriginSession,
  commandFor,
} from "./state.js";
import { icon, type Icon } from "./icons.js";
import { translate, type TextKey } from "./i18n.js";

export interface ViewState {
  catalog: Bootstrap;
  language: Language;
  theme: string;
  reviews: Record<string, Review>;
  view: View;
  filters: Filters;
  age: string;
  selected: Set<string>;
  detailId: string;
  detailTab: string;
  mobileDetail: boolean;
  busy: boolean;
  notice: string;
  error: string;
  copied: boolean;
  activeSession?: Session;
  conversation?: ConversationState;
  targetMessage?: number;
  sessionPage?: SessionPage;
  pageOffset: number;
  listPending: boolean;
  indexProgress: IndexProgress;
  activity: ActivityGroup[];
  activityDays: number;
  noteDraft?: NoteDraft;
  items: (Session | Memory | TrashEntry)[];
}

export function workspaceMarkup(state: ViewState): string {
  const {
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
  } = state;
  const t = (key: TextKey): string => translate(language, key);
  const test = (name: string): string => `data-testid="${name}"`;
  const indexing =
    indexProgress.phase === "scan" || indexProgress.phase === "index";
  const disabled = (): string =>
    busy || indexing || catalog.mode === "static" ? "disabled" : "";
  const filesDisabled = (): string =>
    catalog.background_index && !catalog.index_revision
      ? "disabled"
      : disabled();
  const button = (
    action: string,
    label: string,
    glyph?: Icon,
    extra = "",
  ): string =>
    `<button type="button" data-action="${action}" ${extra}>${glyph ? icon(glyph) : ""}<span>${esc(label)}</span></button>`;
  const sessionTitle = (session: Session): string =>
    session.title ||
    session.first_message.split("\n")[0].slice(0, 140) ||
    t("untitled");
  const providerLabel = (provider: string): string =>
    provider === "claude"
      ? "Claude"
      : provider === "codex"
        ? "Codex"
        : "Antigravity";
  const providerBadge = (provider: string): string =>
    `<span class="provider provider-${esc(provider)}"><span class="provider-dot"></span>${providerLabel(provider)}</span>`;
  const date = (value: string | number, full = false): string => {
    const parsed = new Date(typeof value === "number" ? value * 1000 : value);
    return Number.isNaN(parsed.getTime())
      ? "—"
      : new Intl.DateTimeFormat(
          language,
          full
            ? { dateStyle: "medium", timeStyle: "short" }
            : { month: "short", day: "numeric" },
        ).format(parsed);
  };
  const bytes = (value: number): string =>
    value >= 1048576
      ? `${(value / 1048576).toFixed(1)} MB`
      : `${Math.max(1, Math.round(value / 1024))} KB`;
  const referenceTime = (): number =>
    Math.max(
      Date.parse(catalog.generated_at) / 1000 || 0,
      ...catalog.memories.map((item) => item.timestamp),
    );
  const isStale = (memory: Memory): boolean => stale(memory, referenceTime());
  function selectOptions(
    values: { value: string; label: string }[],
    current: string,
  ): string {
    return values
      .map(
        (option) =>
          `<option value="${esc(option.value)}" ${current === option.value ? "selected" : ""}>${esc(option.label)}</option>`,
      )
      .join("");
  }
  const counts = {
    sessions: sessionPage?.catalog_total ?? catalog.sessions.length,
    memories: catalog.memories.length + (catalog.notes?.length ?? 0),
    trash: catalog.trash.length,
    activity: activity.reduce(
      (total, group) => total + group.sessions.length,
      0,
    ),
  };
  const projectOptions =
    sessionPage?.projects ??
    [
      ...new Set(catalog.sessions.map((session) => session.project_path)),
    ].sort();
  const providerOptions = [
    { value: "all", label: t("allProviders") },
    { value: "claude", label: "Claude" },
    { value: "codex", label: "Codex" },
    { value: "antigravity", label: "Antigravity" },
  ];
  function sidebar(): string {
    return `<aside class="sidebar"><a href="#" class="brand" data-action="home" aria-label="Session Desk">${icon("pages")}<span>Session Desk</span></a><div class="workspace-label">${t("workspace")}</div><nav aria-label="${t("workspace")}">${(["sessions", "activity", "memories", "trash"] as View[]).map((name) => button(`view-${name}`, t(name), name === "sessions" ? "sessions" : name === "memories" ? "memory" : name === "activity" ? "clock" : "trash", `class="nav-item ${view === name ? "active" : ""}" ${test(`nav-${name}`)} ${view === name ? 'aria-current="page"' : ""}`).replace("</button>", `${name === "activity" ? "" : `<span class="nav-count">${counts[name]}</span>`}</button>`)).join("")}</nav><div class="sidebar-bottom"><div class="workspace-mode"><span class="mode-indicator"></span><strong>${t(catalog.mode)}</strong><p>${t(catalog.mode === "demo" ? "demoDescription" : catalog.mode === "local" ? "localDescription" : "staticDescription")}</p></div><div class="preferences"><label class="language-control"><span class="sr-only">${t("language")}</span><select ${test("language-select")} id="language" aria-label="${t("language")}">${selectOptions(
      [
        { value: "en", label: "English" },
        { value: "es", label: "Español" },
      ],
      language,
    )}</select></label>${button("theme", t(theme === "light" ? "dark" : "light"), theme === "light" ? "moon" : "sun", `class="icon-button" ${test("theme-toggle")} aria-label="${t(theme === "light" ? "dark" : "light")}"`)}</div><div class="rail-footer">${icon("shield")}<span>${t("privacy")}</span></div></div></aside>`;
  }
  function toolbar(): string {
    const projects =
      view === "memories"
        ? [...new Set(catalog.memories.map((item) => item.project_path))].sort()
        : projectOptions;
    return `<div class="toolbar"><label class="search-box">${icon("search")}<input id="search" ${test("search")} type="search" maxlength="500" autocomplete="off" placeholder="${t(view === "sessions" ? "searchSessions" : view === "memories" ? "searchMemories" : "searchTrash")}" aria-label="${t("shortcuts")}" value="${esc(filters.query)}"><kbd>/</kbd></label>${
      view !== "trash"
        ? `<div class="filters"><label><span class="sr-only">${t("provider")}</span><select id="provider" ${test("provider-filter")} aria-label="${t("provider")}">${selectOptions(
            view === "memories" ? providerOptions.slice(0, 2) : providerOptions,
            filters.provider,
          )}</select></label><label class="project-filter"><span class="sr-only">${t("project")}</span><select id="project" ${test("project-filter")} aria-label="${t("project")}">${selectOptions([{ value: "", label: t("allProjects") }, ...projects.map((path) => ({ value: path, label: basename(path) || t("unknownProject") }))], filters.project)}</select></label><label><span class="sr-only">${t(view === "sessions" ? "review" : "stale")}</span><select id="${view === "sessions" ? "review" : "age"}" ${test(view === "sessions" ? "review-filter" : "stale-filter")} aria-label="${t(view === "sessions" ? "review" : "stale")}">${
            view === "sessions"
              ? selectOptions(
                  [
                    { value: "all", label: t("allReviews") },
                    { value: "pending", label: t("pending") },
                    { value: "keep", label: t("keep") },
                  ],
                  filters.review,
                )
              : selectOptions(
                  [
                    { value: "all", label: t("allMemories") },
                    { value: "stale", label: t("staleOnly") },
                    { value: "fresh", label: t("freshOnly") },
                  ],
                  age,
                )
          }</select></label></div>`
        : ""
    }</div>`;
  }
  function row(item: Session | Memory): string {
    const session = "session_id" in item;
    const title = session ? sessionTitle(item) : item.name;
    const subtitle = session
      ? item.hit?.snippet || item.first_message
      : item.description;
    const readOnly = session && item.provider === "antigravity";
    return `<article class="item-row ${detailId === item.id ? "is-open" : ""} ${selected.has(item.id) ? "is-selected" : ""}" data-id="${esc(item.id)}" ${test(session ? "session-row" : "memory-row")}><label class="row-check"><input type="checkbox" data-select="${esc(item.id)}" ${test("row-select")} aria-label="${esc(t("selectItem") + ": " + title)}" ${selected.has(item.id) ? "checked" : ""} ${readOnly || (listPending && session) ? "disabled" : filesDisabled()}></label><button type="button" class="row-open" data-open="${esc(item.id)}" ${test("row-open")} aria-expanded="${detailId === item.id}" aria-controls="detail-panel"><span class="row-top">${providerBadge(item.provider)}<time datetime="${esc(item.updated_at)}">${date(item.updated_at)}</time></span><span class="row-title">${esc(title)}</span><span class="row-preview">${esc(subtitle)}</span><span class="row-bottom"><span class="row-project">${icon("folder")}${esc(basename(item.project_path) || t("unknownProject"))}</span>${session ? `<span class="message-count">${item.message_count === null ? t("unknownCount") : item.message_count + " " + t("messages")}</span><span class="review-badge ${(reviews[item.id] ?? "pending") === "keep" ? "kept" : ""}">${icon(reviews[item.id] === "keep" ? "check" : "clock")}${t(reviews[item.id] === "keep" ? "keep" : "pending")}</span>` : `<span class="memory-type">${esc(item.memory_type)}</span>${isStale(item) ? `<span class="stale-badge">${t("stale")}</span>` : ""}`}</span></button></article>`;
  }
  function emptyState(filtered: boolean): string {
    return `<div class="empty-state">${icon(view === "sessions" ? "sessions" : view === "memories" ? "memory" : "trash")}<h2>${t(filtered ? "noResults" : "empty")}</h2><p>${t(filtered ? "noResultsDescription" : view === "sessions" ? "emptySessions" : view === "memories" ? "emptyMemories" : "emptyTrash")}</p>${filtered ? button("clear-filters", t("clearFilters"), undefined, 'class="secondary"') : ""}</div>`;
  }
  function pagination(): string {
    if (view !== "sessions" || !sessionPage || sessionPage.total <= 50)
      return "";
    return `<div class="page-controls">${button("page-previous", t("previous"), "back", `class="secondary" ${!pageOffset || listPending ? "disabled" : ""}`)}<span>${pageOffset + 1}–${Math.min(pageOffset + 50, sessionPage.total)} / ${sessionPage.total}</span>${button("page-next", t("next"), "arrow", `class="secondary" ${pageOffset + 50 >= sessionPage.total || listPending ? "disabled" : ""}`)}</div>`;
  }
  function list(items: (Session | Memory | TrashEntry)[]): string {
    const hasFilters = Boolean(
      filters.query ||
      filters.provider !== "all" ||
      filters.project ||
      filters.review !== "all" ||
      age !== "all",
    );
    if (view === "trash")
      return `<section class="trash-list" aria-label="${t("trash")}">${items.length ? (items as TrashEntry[]).map((item) => `<article class="trash-row" data-id="${esc(item.id)}">${icon(item.kind === "session" ? "sessions" : "memory")}<div><h2>${esc(item.title)}</h2><p>${providerLabel(item.provider)}<span>·</span>${esc(basename(item.project_path))}<span>·</span>${t("deleted")} ${date(item.deleted_at)}</p></div>${button("restore", t("restore"), "refresh", `${test("restore-item")} data-id="${esc(item.id)}" class="secondary" ${filesDisabled()}`)}</article>`).join("") : emptyState(hasFilters)}</section>`;
    const selectable = items.filter(
      (item) => item.provider !== "antigravity",
    ).length;
    return `<section class="item-list" aria-label="${t(view)}"><div class="list-heading"><label class="select-all"><input type="checkbox" ${test("select-all")} id="select-all" aria-label="${t("selectAll")}" ${selectable && selected.size === selectable ? "checked" : ""} ${!selectable || (view === "sessions" && listPending) ? "disabled" : filesDisabled()}></label><span>${view === "sessions" && listPending ? t("loadingSessions") : `${sessionPage && view === "sessions" ? sessionPage.total : items.length} ${t("visible")}`}</span><div class="sort-controls">${button("sort-title", t("title"), undefined, `class="sort-button ${filters.sort === "title" ? "current" : ""}" aria-label="${t("title")}, ${t(filters.ascending ? "ascending" : "descending")}"`)}${button("sort-updated", t("updated"), "sort", `class="sort-button ${filters.sort === "updated" ? "current" : ""}" ${test("sort-updated")} aria-label="${t("updated")}, ${t(filters.ascending ? "ascending" : "descending")}"`)}</div></div><div class="list-scroll">${view === "sessions" && listPending ? "" : items.length ? (items as (Session | Memory)[]).map(row).join("") : emptyState(hasFilters)}</div>${pagination()}<div class="list-footer">${icon("check")}<span>${t("selectToManage")}</span></div></section>`;
  }
  function metadata(items: [TextKey, string][]): string {
    return `<dl class="metadata">${items.map(([key, value]) => `<div><dt>${t(key)}</dt><dd>${esc(value || "—")}</dd></div>`).join("")}</dl>`;
  }
  function highlighted(text: string): string {
    if (!filters.query.trim()) return esc(text);
    const tokens = filters.query
      .trim()
      .split(/\s+/)
      .map((token) => token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const pattern = new RegExp(tokens.join("\\s+"), "giu");
    const parts = [];
    let offset = 0;
    for (const match of text.matchAll(pattern)) {
      parts.push(
        esc(text.slice(offset, match.index)),
        `<mark>${esc(match[0])}</mark>`,
      );
      offset = match.index + match[0].length;
    }
    return parts.join("") + esc(text.slice(offset));
  }
  function conversationMarkup(session: Session): string {
    if (session.has_transcript === false)
      return `<p class="muted">${t("metadataOnly")}</p>`;
    const page = conversation?.page;
    const messages = page?.messages ?? session.messages;
    const offset = page?.offset ?? 0;
    const preview = catalog.mode === "static" || (!page && messages.length > 0);
    const status = conversation?.loading
      ? `<p class="muted" role="status">${t("loadingConversation")}</p>`
      : conversation?.failed
        ? `<div class="notice error" role="alert">${t("conversationError")}${button("conversation-retry", t("retry"), "refresh", 'class="secondary"')}</div>`
        : "";
    const markup = messages
      .map((message, index) => {
        const position = offset + index;
        const active = position === targetMessage;
        return `<article class="message message-${message.role}${active ? " message-hit" : ""}" data-position="${position}" tabindex="-1"><header><span class="speaker-symbol">${message.role === "user" ? icon("terminal") : icon("pages")}</span><strong>${message.role === "user" ? t("you") : providerLabel(session.provider)}</strong><span class="message-number">${String(position + 1).padStart(2, "0")}</span></header><div class="message-text">${active ? highlighted(message.text) : esc(message.text)}</div>${catalog.mode !== "static" ? button("note-add", t("addNote"), undefined, `class="text-button message-action" data-position="${position}" ${disabled()}`) : ""}</article>`;
      })
      .join("");
    const navigation =
      catalog.paged && page && page.total > 40
        ? `<div class="page-controls">${button("conversation-page", t("previous"), "back", `class="secondary" data-offset="${Math.max(0, offset - 40)}" ${!offset ? "disabled" : ""}`)}<span>${offset + 1}–${offset + messages.length} / ${page.total}</span>${button("conversation-page", t("next"), "arrow", `class="secondary" data-offset="${offset + 40}" ${offset + messages.length >= page.total ? "disabled" : ""}`)}</div>`
        : "";
    return (
      status +
      (preview ? `<p class="muted">${t("previewConversation")}</p>` : "") +
      (markup || (status ? "" : `<p class="muted">${t("noMessages")}</p>`)) +
      navigation
    );
  }
  function sessionContext(): string {
    const context = conversation?.page?.context;
    if (!context?.user && !context?.assistant) return "";
    return `<details class="session-context" data-session="${esc(detailId)}"><summary>${t("resumeContext")}</summary>${(
      ["user", "assistant"] as const
    )
      .map((role) => {
        const message = context[role];
        if (!message) return "";
        return `<section><h3>${t(role === "user" ? "lastRequest" : "lastReply")}</h3><p>${esc(message.text.length > 600 ? message.text.slice(0, 600) + "…" : message.text)}</p>${button("context-message", t("openMessage"), "arrow", `class="text-button" data-position="${message.position}" data-offset="${Math.floor(message.position / 40) * 40}"`)}</section>`;
      })
      .join(
        "",
      )}${button("copy-context", t("copyContext"), "copy", 'class="secondary"')}</details>`;
  }
  function sessionDetail(session: Session): string {
    const command = commandFor(session);
    const count =
      conversation?.page && catalog.paged
        ? conversation.page.total
        : session.message_count;
    const overview =
      detailTab === "conversation"
        ? conversationMarkup(session)
        : metadata([
            ["provider", providerLabel(session.provider)],
            ["project", session.project_path],
            ["branch", session.branch],
            ["sessionId", session.session_id],
            ["file", session.file_path],
            ["modified", date(session.updated_at, true)],
            ["size", bytes(session.size_bytes)],
            [
              "prompts",
              session.prompt_count == null
                ? t("unknownCount")
                : String(session.prompt_count),
            ],
          ]);
    return `<div class="detail-title">${providerBadge(session.provider)}<h2>${esc(sessionTitle(session))}</h2><div class="detail-meta"><span>${icon("folder")}${esc(basename(session.project_path) || t("unknownProject"))}</span>${session.branch ? `<span>${icon("branch")}${esc(session.branch)}</span>` : ""}${session.variant ? `<span>${{ cli: "CLI", app: "App", ide: "IDE" }[session.variant]}</span>` : ""}</div></div><div class="resume-box"><div><h3>${t("resume")}</h3><p>${t(command ? "commandHint" : session.variant === "app" ? "appResumeHint" : "ideResumeHint")}</p></div>${button("copy", t(copied ? "copied" : command ? "copyCommand" : "copyTitleId"), copied ? "check" : "copy", `class="primary" ${test("copy-command")}`)}${command ? `<code class="resume-command">${esc(command)}</code>` : ""}</div>${sessionContext()}<div class="detail-tabs" role="tablist" aria-label="${t("details")}">${(["conversation", "details"] as const).map((tab) => button(`tab-${tab}`, t(tab), undefined, `role="tab" id="tab-${tab}" aria-selected="${detailTab === tab}" aria-controls="tab-content" tabindex="${detailTab === tab ? 0 : -1}" class="${detailTab === tab ? "active" : ""}"`)).join("")}<span>${count == null ? "" : count + " " + t("messages")}</span></div><div class="detail-content" id="tab-content" role="tabpanel" aria-labelledby="tab-${detailTab}" tabindex="0">${overview}</div><div class="review-bar"><span>${t(session.provider === "antigravity" ? "antigravityReadOnly" : "review")}</span><div>${button("review-keep", t("keep"), "check", `class="review-button ${reviews[session.id] === "keep" ? "active" : ""}" ${test("review-keep")} aria-pressed="${reviews[session.id] === "keep"}" aria-label="${t("markKeep")}" ${disabled()}`)}${button("review-pending", t("pending"), "clock", `class="review-button ${reviews[session.id] !== "keep" ? "active" : ""}" ${test("review-pending")} aria-pressed="${reviews[session.id] !== "keep"}" aria-label="${t("markPending")}" ${disabled()}`)}</div></div>`;
  }
  function memoryDetail(memory: Memory): string {
    const origin =
      memory.origin_row_id ??
      resolveOriginSession(catalog.sessions, memory)?.id;
    const body = wikiParts(memory.body)
      .map((part) => {
        if (!part.target) return esc(part.text);
        const linked = resolveMemoryLink(
          catalog.memories,
          part.target,
          memory.project_path,
        );
        return linked
          ? `<button class="wiki-link" data-memory="${esc(linked.id)}" title="${t("linkedMemory")}">${esc(part.text)}</button>`
          : `<span class="broken-link" title="${t("brokenLink")}" data-testid="broken-link">${esc(part.text)} ${icon("link")}<span class="sr-only"> (${t("brokenLink")})</span></span>`;
      })
      .join("");
    return `<div class="detail-title">${providerBadge(memory.provider)}<h2>${esc(memory.name)}</h2><p class="memory-description">${esc(memory.description)}</p><div class="detail-meta"><span>${icon("folder")}${esc(basename(memory.project_path))}</span><span>${esc(memory.memory_type)}</span>${isStale(memory) ? `<span class="stale-badge">${t("stale")}</span>` : ""}</div></div><div class="memory-origin"><span>${icon("link")}${t("origin")}</span>${origin ? button("origin", t("openOrigin"), "arrow", `data-id="${esc(origin)}" class="text-button" ${test("open-origin")}`) : `<p>${t("missingOrigin")}</p>`}</div><div class="detail-content memory-content"><div class="memory-body">${body}</div>${metadata(
      [
        ["file", memory.file_path],
        ["modified", date(memory.updated_at, true)],
        ["size", bytes(memory.size_bytes)],
      ],
    )}</div>`;
  }
  function detail(): string {
    const item =
      view === "sessions"
        ? (activeSession ??
          catalog.sessions.find((session) => session.id === detailId))
        : catalog.memories.find((memory) => memory.id === detailId);
    return `<aside class="detail-panel ${item ? "has-detail" : ""}" id="detail-panel" ${test("detail-panel")} aria-label="${t("details")}">${item ? `<div class="detail-topline">${button("close-detail", t("backList"), "back", 'class="mobile-back text-button"')}<span class="detail-section-label">${t(view === "sessions" ? "session" : "memory")}</span>${button("close-detail", t("closeDetail"), "close", `class="icon-button close-detail" aria-label="${t("closeDetail")}"`)}</div>${"session_id" in item ? sessionDetail(item) : memoryDetail(item)}` : `<div class="detail-placeholder">${icon("pages")}<h2>${t(view === "sessions" ? "detailPrompt" : "memoryPrompt")}</h2><p>${t(view === "sessions" ? "detailDescription" : "memoryDescription")}</p></div>`}</aside>`;
  }
  function activityMarkup(): string {
    return `<div class="toolbar"><div class="filters"><label><span class="sr-only">${t("activity")}</span><select id="activity-days">${selectOptions(
      [
        { value: "7", label: t("days7") },
        { value: "30", label: t("days30") },
      ],
      String(activityDays),
    )}</select></label><label><span class="sr-only">${t("provider")}</span><select id="provider" aria-label="${t("provider")}">${selectOptions(providerOptions, filters.provider)}</select></label></div></div><div class="analysis-groups">${activity.length ? activity.map((group) => `<details class="analysis-group" open><summary>${esc(group.project || t("unknownProject"))}<span>${group.sessions.length}</span></summary><ul>${group.sessions.map((session) => `<li>${button("activity-session", session.title || t("untitled"), undefined, `class="text-button" data-id="${esc(session.id)}"`)}<span>${providerBadge(session.provider)} <time>${date(session.updated_at)}</time>${session.activity_source !== "recorded" ? ` · ${t("dateFromFile")}` : ""}</span></li>`).join("")}</ul></details>`).join("") : `<p class="muted">${t("noActivity")}</p>`}</div>`;
  }
  function notesMarkup(): string {
    const query = filters.query.trim().toLocaleLowerCase();
    const notes =
      catalog.notes?.filter(
        (note) =>
          !query ||
          `${note.title} ${note.body}`.toLocaleLowerCase().includes(query),
      ) ?? [];
    if (!notes.length) return "";
    return `<section class="analysis-groups" aria-label="${t("notes")}"><h2>${t("notes")}</h2>${notes.map((note) => `<article class="analysis-group note"><h3>${esc(note.title)}</h3><p>${esc(note.body)}</p><div>${note.source_available ? button("origin", t("openMessage"), "arrow", `data-id="${esc(note.session_id)}" data-position="${note.position}" class="text-button"`) : `<span class="muted">${t("sourceUnavailable")}</span>`}${button("note-edit", t("editNote"), undefined, `data-id="${esc(note.id)}" class="secondary" ${disabled()}`)}${button("note-export", t("exportNote"), undefined, `data-id="${esc(note.id)}" class="secondary"`)}</div></article>`).join("")}</section>`;
  }
  function noteDialog(): string {
    if (!noteDraft) return "";
    return `<dialog id="note-dialog" class="note-dialog" aria-labelledby="note-heading"><form id="note-form"><h2 id="note-heading">${t(noteDraft.id ? "editNote" : "addNote")}</h2><label>${t("title")}<input name="title" maxlength="200" required autofocus value="${esc(noteDraft.title)}"></label><label>${t("noteBody")}<textarea name="body" rows="6" maxlength="50000" required>${esc(noteDraft.body)}</textarea></label><p role="alert" class="muted"></p><div class="dialog-actions">${button("cancel-note", t("cancel"), undefined, 'class="secondary"')}<button class="primary" type="submit">${t("save")}</button></div></form></dialog>`;
  }
  const indexStatus =
    indexProgress.phase === "scan"
      ? t("scanningHistory")
      : indexProgress.phase === "index"
        ? `${t("indexingHistory")} · ${indexProgress.completed.toLocaleString(language)}${indexProgress.total ? ` / ${indexProgress.total.toLocaleString(language)}` : ""}`
        : "";
  const descriptions = {
    sessions: "sessionsDescription",
    memories: "memoriesDescription",
    trash: "trashDescription",
    activity: "activityDescription",
  } as const;
  const layout =
    view === "activity"
      ? activityMarkup()
      : `${toolbar()}${selected.size ? `<div class="bulk-bar"><strong>${selected.size} ${t("selected")}</strong>${button("clear-selection", t("clearSelection"), undefined, 'class="text-button"')}${button("trash", t("moveTrash"), "trash", `class="danger-button" ${test("trash-selected")} ${filesDisabled()}`)}</div>` : ""}<div class="work-area ${view === "trash" ? "trash-area" : ""}">${list(items)}${view !== "trash" ? detail() : ""}</div>${view === "memories" ? notesMarkup() : ""}`;
  return `${sidebar()}<main class="workspace ${mobileDetail ? "mobile-detail" : ""} ${view === "memories" && catalog.notes?.length ? "has-notes" : ""}"><header class="page-header"><div><h1>${t(view)}</h1><p>${t(descriptions[view])}</p></div><div class="header-actions">${catalog.mode === "local" ? button("refresh", t("refresh"), "refresh", `class="secondary" ${test("refresh")} ${busy || indexStatus ? "disabled" : ""}`) : ""}<span class="private-label">${icon("shield")}${t("privacy")}</span></div></header><div class="summary-strip"><span><strong>${counts[view]}</strong> ${t(view === "sessions" || view === "activity" ? "conversations" : view === "memories" ? "memoryCount" : "trashCount")}</span>${view === "sessions" ? `<span><strong>${projectOptions.length}</strong> ${t("projects")}</span><span class="summary-providers">Claude Code <span>·</span> Codex <span>·</span> Antigravity</span>` : ""}<span class="snapshot-date">${t("generated")} ${date(catalog.generated_at)}</span></div>${catalog.mode === "demo" ? `<div class="demo-banner"><span>${icon("terminal")}${t("demoBanner")}</span>${button("reset", t("resetDemo"), "refresh", `class="text-button" ${test("reset-demo")}`)}</div>` : catalog.mode === "static" ? `<div class="static-banner">${icon("shield")}${t("readOnly")}</div>` : ""}${error ? `<div class="notice error" role="alert"><span>${esc(error)}</span>${button("dismiss-error", t("dismiss"), "close", 'class="icon-button"')}</div>` : ""}${notice ? `<div class="notice success" role="status"><span>${esc(notice)}</span>${button("dismiss-notice", t("dismiss"), "close", 'class="icon-button"')}</div>` : ""}${indexProgress.phase === "error" ? `<p class="notice error" role="alert">${t("indexFailed")}</p>` : ""}${indexStatus ? `<p class="notice" role="status" data-testid="index-progress">${esc(indexStatus)}</p>` : ""}${catalog.warnings.length ? `<details class="warnings"><summary>${t("warnings")} (${catalog.warnings.length})</summary>${catalog.warnings.map((warning) => `<p>${esc(warning.message)}${warning.path ? `<code>${esc(warning.path)}</code>` : ""}</p>`).join("")}</details>` : ""}${layout}</main>${noteDialog()}<dialog id="trash-dialog" aria-labelledby="dialog-title"><form method="dialog"><div class="dialog-icon">${icon("trash")}</div><h2 id="dialog-title">${t("confirmTitle")}</h2><p>${selected.size} ${t("selected")}. ${t("confirmDescription")}</p><div class="dialog-actions"><button class="secondary" value="cancel" autofocus>${t("cancel")}</button><button type="button" data-action="confirm-trash" class="danger-button" ${test("confirm-trash")}>${t("confirmTrash")}</button></div></form></dialog>`;
}
