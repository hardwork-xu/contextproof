"""Stable, JSON-friendly contracts shared by indexing, retrieval, and evidence."""

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Chunk:
    id: str
    path: str
    start_line: int
    end_line: int
    text: str
    symbol: str
    kind: str
    file_sha256: str


@dataclass
class Snapshot:
    id: str
    files: dict[str, str]
    chunks: list[Chunk]
    edges: list[tuple[str, str]]
    stats: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float
    reasons: tuple[str, ...]


def as_json(value):
    return asdict(value)
