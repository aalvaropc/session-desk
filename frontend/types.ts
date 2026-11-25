export type Provider = "claude" | "codex";
export type Review = "keep" | "pending";
export type View = "sessions" | "memories" | "trash";
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
  message_count: number;
  prompt_count: number;
  messages: ChatMessage[];
  match: string;
  version: string;
}
export interface Memory {
  id: string;
  provider: Provider;
  name: string;
  description: string;
  memory_type: string;
  origin_session_id: string;
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
