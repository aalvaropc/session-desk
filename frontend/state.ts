import type { Filters, Memory, Review, Session } from "./types.js";
interface StorageReader {
  getItem(key: string): string | null;
}
export function readReview(storage: StorageReader): Record<string, Review> {
  try {
    const value: unknown = JSON.parse(
      storage.getItem("session-desk:review:v1") ?? "{}",
    );
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(
      Object.entries(value).filter(
        (entry): entry is [string, Review] =>
          entry[1] === "keep" || entry[1] === "pending",
      ),
    );
  } catch {
    return {};
  }
}
export function readPreference<T extends string>(
  storage: StorageReader,
  key: string,
  choices: readonly T[],
  fallback: T,
): T {
  try {
    const value: unknown = JSON.parse(
      storage.getItem(`session-desk:${key}:v1`) ?? "null",
    );
    return typeof value === "string" && choices.includes(value as T)
      ? (value as T)
      : fallback;
  } catch {
    return fallback;
  }
}
export function persist(key: string, value: unknown): void {
  try {
    localStorage.setItem(`session-desk:${key}:v1`, JSON.stringify(value));
  } catch {
    return;
  }
}
export function projectContains(project: string, path: string): boolean {
  const root = project.replace(/\\/g, "/").replace(/\/+$/, "") || "/";
  const child = path.replace(/\\/g, "/").replace(/\/+$/, "") || "/";
  if (!project || !path) return false;
  if (root === child) return true;
  if (root.startsWith("/") || root.startsWith("~/"))
    return child.startsWith(root === "/" ? "/" : root + "/");
  if (/^[a-z]:/i.test(root))
    return child.toLowerCase().startsWith(root.toLowerCase() + "/");
  return false;
}
export function filterSessions(
  sessions: Session[],
  filters: Filters,
  reviews: Record<string, Review>,
): Session[] {
  const query = filters.query.trim().toLocaleLowerCase();
  return sessions
    .filter(
      (session) =>
        (filters.provider === "all" || session.provider === filters.provider) &&
        (!filters.project ||
          projectContains(filters.project, session.project_path)) &&
        (filters.review === "all" ||
          (reviews[session.id] ?? "pending") === filters.review) &&
        (!query ||
          [
            session.title,
            session.first_message,
            session.project_path,
            session.branch,
            session.session_id,
            ...session.messages.map((message) => message.text),
          ]
            .join(" ")
            .toLocaleLowerCase()
            .includes(query)),
    )
    .sort(
      (a, b) =>
        (filters.sort === "title"
          ? a.title.localeCompare(b.title)
          : a.timestamp - b.timestamp) * (filters.ascending ? 1 : -1),
    );
}
export function visibleSelection(
  selected: Set<string>,
  items: { id: string }[],
): Set<string> {
  const visible = new Set(items.map((item) => item.id));
  return new Set([...selected].filter((id) => visible.has(id)));
}
export function isInteractive(
  target: { closest(selector: string): unknown } | null,
): boolean {
  return Boolean(
    target?.closest(
      'input, button, select, textarea, a, summary, [contenteditable]:not([contenteditable="false"]), [role="button"], [role="tab"], [role="textbox"], [role="combobox"], dialog',
    ),
  );
}
export function wikiParts(text: string): { text: string; target?: string }[] {
  const result: { text: string; target?: string }[] = [];
  let cursor = 0;
  for (const match of text.matchAll(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g)) {
    const index = match.index ?? 0;
    if (index > cursor) result.push({ text: text.slice(cursor, index) });
    result.push({ text: match[2] ?? match[1], target: match[1] });
    cursor = index + match[0].length;
  }
  if (cursor < text.length) result.push({ text: text.slice(cursor) });
  return result;
}
export const escapeHTML = (value: unknown): string =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        character
      ] ?? character,
  );
export const basename = (path: string): string =>
  path.replace(/\/$/, "").split(/[\\/]/).pop() || path;
export const stale = (
  memory: { timestamp: number },
  reference: number,
): boolean => reference - memory.timestamp > 90 * 86400;

export function resolveMemoryLink(
  memories: Memory[],
  target: string,
  projectPath: string,
): Memory | undefined {
  const normalize = (value: string): string =>
    value
      .split("#")[0]
      .replace(/\.md$/i, "")
      .toLocaleLowerCase()
      .replace(/[-_\s]+/g, "");
  const needle = normalize(target);
  return memories.find(
    (memory) =>
      memory.project_path === projectPath &&
      [memory.name, basename(memory.file_path)].some(
        (value) => normalize(value) === needle,
      ),
  );
}

export function resolveOriginSession(
  sessions: Session[],
  memory: Pick<Memory, "origin_session_id" | "provider" | "project_path">,
): Session | undefined {
  return sessions.find(
    (session) =>
      session.session_id === memory.origin_session_id &&
      session.provider === memory.provider &&
      session.project_path === memory.project_path,
  );
}

export function commandFor(session: Session): string {
  const id = `'${session.session_id.replace(/'/g, "'\\''")}'`;
  if (session.provider === "antigravity")
    return session.variant === "cli" ? `agy --conversation ${id}` : "";
  return session.provider === "claude"
    ? `claude --resume ${id}`
    : `codex resume ${id}`;
}
