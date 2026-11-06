from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, TypedDict


class Message(TypedDict):
    role: str
    text: str


class BatchError(TypedDict):
    id: str
    code: str
    message: str


@dataclass
class Serializable:
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Session(Serializable):
    id: str
    session_id: str
    provider: str
    title: str
    first_message: str
    project_path: str
    file_path: str
    branch: str
    updated_at: str
    timestamp: int
    size_bytes: int
    message_count: int
    prompt_count: int
    messages: List[Message]
    match: str
    version: str


@dataclass
class Memory(Serializable):
    id: str
    provider: str
    name: str
    description: str
    memory_type: str
    origin_session_id: str
    body: str
    project_path: str
    file_path: str
    updated_at: str
    timestamp: int
    size_bytes: int
    version: str


@dataclass
class TrashEntry(Serializable):
    id: str
    kind: str
    provider: str
    title: str
    project_path: str
    deleted_at: str
    size_bytes: int


@dataclass
class ScanWarning(Serializable):
    code: str
    message: str
    path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        if self.path is None:
            result.pop("path")
        return result


@dataclass
class BatchResult(Serializable):
    done: List[str]
    errors: List[BatchError]
