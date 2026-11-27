import type {
  ActivityGroup,
  ContextMessage,
  ConversationPage,
  Note,
  Session,
} from "./types.js";
import { translate, type TextKey } from "./i18n.js";

export function embeddedConversation(session: Session): ConversationPage {
  const messages = session.messages;
  const context: ConversationPage["context"] = {};
  messages.forEach((message, position) => {
    context[message.role] = { text: message.text, position };
  });
  return { messages, total: messages.length, offset: 0, context };
}

export function contextMarkdown(
  session: Session,
  context: Partial<Record<"user" | "assistant", ContextMessage>>,
  language: "en" | "es",
): string {
  const t = (key: TextKey): string => translate(language, key);
  const fields = [
    session.project_path && `- ${t("project")}: ${session.project_path}`,
    session.branch && `- ${t("branch")}: ${session.branch}`,
  ].filter(Boolean);
  const sections = [
    context.user && `## ${t("lastRequest")}\n\n${context.user.text}`,
    context.assistant && `## ${t("lastReply")}\n\n${context.assistant.text}`,
  ].filter(Boolean);
  return (
    [
      `# ${session.title || session.first_message || session.session_id}`,
      fields.join("\n"),
      ...sections,
    ]
      .filter(Boolean)
      .join("\n\n") + "\n"
  );
}

export function localActivity(
  sessions: Session[],
  reference: number,
  days: number,
  provider: string,
): ActivityGroup[] {
  const groups = new Map<string, ActivityGroup>();
  for (const session of [...sessions].sort(
    (a, b) => b.timestamp - a.timestamp,
  )) {
    if (
      session.timestamp < reference - days * 86400 ||
      (provider !== "all" && session.provider !== provider)
    )
      continue;
    const project = session.project_path;
    const group = groups.get(project) ?? { project, sessions: [] };
    group.sessions.push({
      ...session,
      title: session.title || session.first_message,
    });
    groups.set(project, group);
  }
  return [...groups.values()];
}

export function noteMarkdown(note: Note): string {
  return `# ${note.title.replace(/\s+/g, " ")}\n\n${note.body}\n\nSource: ${note.session_id} / message ${note.position + 1}\n`;
}
