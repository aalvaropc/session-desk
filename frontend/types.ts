export type Provider = "claude" | "codex" | "antigravity";
export type Review = "keep" | "pending";
export type View = "sessions" | "memories" | "trash" | "activity";
export const sessionTabs = [
  "conversation",
  "resumeContext",
  "details",
] as const;
export type SessionTab = (typeof sessionTabs)[number];
export type Language = "en" | "es";
export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
}
export interface Session {
  id: string;
  session_id: string;
  provider: Provider;
  title: string;
  first_message: string;
  project_path: string;
  file_path: string;
  branch: string;
  updated_at: string;
  timestamp: number;
  size_bytes: number;
  message_count: number | null;
  prompt_count: number | null;
  messages: ChatMessage[];
  match: string;
  version: string;
  variant?: "cli" | "app" | "ide";
  has_transcript?: boolean;
  activity_source?: "recorded" | "file";
  hit?: { position: number; snippet: string } | null;
  review?: Review;
}
export interface Memory {
  id: string;
  provider: Provider;
  name: string;
  description: string;
  memory_type: string;
  origin_session_id: string;
  origin_row_id?: string | null;
  body: string;
  project_path: string;
  file_path: string;
  updated_at: string;
  timestamp: number;
  size_bytes: number;
  version: string;
}
export interface TrashEntry {
  id: string;
  kind: "session" | "memory";
  provider: Provider;
  title: string;
  project_path: string;
  deleted_at: string;
  size_bytes: number;
}
export interface Bootstrap {
  sessions: Session[];
  paged?: boolean;
  workspace_id?: string;
  background_index?: boolean;
  index_revision?: number;
  index_ready?: boolean;
  notes?: Note[];
  memories: Memory[];
  trash: TrashEntry[];
  generated_at: string;
  mode: "local" | "demo" | "static";
  token: string | null;
  warnings: { code: string; message: string; path?: string }[];
}
export interface Filters {
  query: string;
  provider: string;
  project: string;
  review: string;
  sort: "updated" | "title";
  ascending: boolean;
}

export interface SessionPage {
  sessions: Session[];
  total: number;
  catalog_total: number;
  projects: string[];
}
export type IndexProgress =
  | { phase: "idle" | "scan" | "error"; revision?: number }
  | {
      phase: "index";
      completed: number;
      total: number;
      revision?: number;
      available?: number;
    };
export interface ContextMessage {
  position: number;
  text: string;
}
export interface ConversationPage {
  messages: ChatMessage[];
  total: number;
  offset: number;
  context: Partial<Record<ChatMessage["role"], ContextMessage>>;
}
export interface ConversationState {
  id: string;
  version: string;
  page?: ConversationPage;
  loading: boolean;
  failed: boolean;
  offset: number;
}
export interface Note {
  id: string;
  session_id: string;
  position: number;
  title: string;
  body: string;
  updated_at: number;
  source_available: boolean;
}
export interface NoteDraft {
  id?: string;
  version?: string;
  session_id: string;
  position: number;
  title: string;
  body: string;
}
export interface ActivityGroup {
  project: string;
  sessions: Pick<
    Session,
    "id" | "title" | "provider" | "updated_at" | "activity_source"
  >[];
}
