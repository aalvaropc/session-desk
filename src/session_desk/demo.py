from __future__ import annotations

import datetime
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .sessions import SessionStore

SCENARIOS = (
    (
        "atlas-web",
        "Design accessible keyboard navigation",
        "Add arrow-key navigation and preserve focus when the list updates.",
        "Accessibility",
        "feat/keyboard-navigation",
    ),
    (
        "atlas-web",
        "A calmer onboarding flow",
        "Simplify the first-run experience and explain each permission at the point it matters.",
        "Product design",
        "feat/onboarding",
    ),
    (
        "api-gateway",
        "Trace a delayed webhook delivery",
        "Follow the request through the retry queue and add a regression test for the timeout.",
        "Investigation",
        "fix/webhook-timeout",
    ),
    (
        "design-system",
        "Build a consistent spacing scale",
        "Replace arbitrary spacing values with shared tokens for dense and comfortable layouts.",
        "Design system",
        "feat/spacing-tokens",
    ),
    (
        "session-desk",
        "Make session recovery resumable",
        "Handle interruption between filesystem moves without overwriting an existing conversation.",
        "Reliability",
        "feat/recovery",
    ),
    (
        "atlas-web",
        "Review the checkout error states",
        "Show recovery actions for declined cards, expired sessions and network failures.",
        "UX writing",
        "fix/checkout-feedback",
    ),
    (
        "api-gateway",
        "Reduce database round trips",
        "Inspect the query plan and batch the repeated account lookups.",
        "Performance",
        "perf/account-lookups",
    ),
    (
        "design-system",
        "Document component decisions",
        "Record why buttons use native semantics and how focus is restored after a dialog.",
        "Documentation",
        "docs/components",
    ),
    (
        "session-desk",
        "Package a completely local demo",
        "Bundle frontend resources into the Python wheel and use synthetic conversations.",
        "Distribution",
        "feat/demo",
    ),
    (
        "api-gateway",
        "Test idempotent payment handling",
        "Prove that concurrent requests with the same key cannot create two ledger entries.",
        "Testing",
        "test/idempotency",
    ),
    (
        "atlas-web",
        "Adapt the activity list for small screens",
        "Keep the first useful item near search and move details into a dedicated mobile pane.",
        "Responsive UI",
        "feat/mobile-list",
    ),
    (
        "design-system",
        "Explore a readable dark theme for long investigation sessions",
        "Measure contrast for secondary text, selected rows, inputs and destructive controls.",
        "Accessibility",
        "feat/dark-theme",
    ),
)


def write_records(path: Path, records: list[dict], timestamp: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )
    os.utime(path, (timestamp, timestamp))


@contextmanager
def demo_store() -> Iterator[SessionStore]:
    with tempfile.TemporaryDirectory(prefix="session-desk-demo-") as directory:
        base = Path(directory)
        claude_root, codex_root = base / "claude", base / "codex"
        now = datetime.datetime.now().timestamp()
        for index, (project, title, request, topic, branch) in enumerate(SCENARIOS):
            timestamp = now - index * 8100
            sid = f"demo-{index + 1:02d}"
            project_path = f"~/Projects/{project}"
            answer = f"I traced the current behavior and made a focused change.\n\nThe {topic.lower()} check now covers the important edge cases. The result is ready to inspect before continuing."
            records: list[dict[str, Any]]
            if index % 2 == 0:
                path = claude_root / "projects" / project / f"{sid}.jsonl"
                records = [
                    {"type": "custom-title", "customTitle": title},
                    {
                        "type": "user",
                        "cwd": project_path,
                        "gitBranch": branch,
                        "message": {"content": request},
                    },
                    {"type": "assistant", "message": {"content": answer}},
                    {
                        "type": "user",
                        "message": {
                            "content": "Walk me through the tradeoff and the next useful check."
                        },
                    },
                    {
                        "type": "assistant",
                        "message": {
                            "content": "The change keeps the existing workflow and makes failure explicit. Next, run the integration check against a realistic fixture, then inspect the result with keyboard navigation."
                        },
                    },
                ]
            else:
                path = codex_root / "sessions" / "2026" / "11" / f"rollout-{sid}.jsonl"
                records = [
                    {
                        "type": "session_meta",
                        "payload": {"id": sid, "cwd": project_path, "git": {"branch": branch}},
                    },
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": title + "\n\n" + request}],
                        },
                    },
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": answer}],
                        },
                    },
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": "Add a focused regression test and explain how to verify the result.",
                                }
                            ],
                        },
                    },
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "The regression exercises the original failure with a small fixture. It fails before the change and passes afterward. I also checked the existing suite and the error recovery path.",
                                }
                            ],
                        },
                    },
                ]
            write_records(path, records, timestamp)
        memories = (
            (
                "atlas-web",
                "accessibility.md",
                "Keyboard conventions",
                "project",
                "Keep focus on the same control after updating a row. Use native buttons for actions.\n\nRelated: [[writing-guidelines]].",
                "demo-01",
                1,
            ),
            (
                "atlas-web",
                "writing-guidelines.md",
                "Writing guidelines",
                "feedback",
                "Use concrete action labels. Explain the next useful step when an operation fails.\n\nRelated: [[accessibility]].",
                "demo-01",
                3,
            ),
            (
                "session-desk",
                "recovery.md",
                "Recovery guarantees",
                "project",
                "Moving a session is reversible. Interrupted operations must remain recoverable without replacing a new file.\n\nRelated: [[release-checklist]].",
                "demo-05",
                100,
            ),
            (
                "design-system",
                "type.md",
                "Typography decisions",
                "reference",
                "Use IBM Plex Sans for interface text and a system monospace for paths. Keep the conversation as the primary content.",
                "demo-04",
                8,
            ),
        )
        for project, filename, name, memory_type, body, origin, age in memories:
            path = claude_root / "projects" / project / "memory" / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"---\nname: {name}\ndescription: Conventions from {project}\ntype: {memory_type}\noriginSessionId: {origin}\n---\n{body}\n",
                encoding="utf-8",
            )
            timestamp = now - age * 86400
            os.utime(path, (timestamp, timestamp))
        yield SessionStore(claude_root, codex_root)
