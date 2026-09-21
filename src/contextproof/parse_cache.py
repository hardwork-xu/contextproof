"""Disposable local AST cache using JSON rather than executable pickle data.

The cache is a trusted local optimization, not an authenticated proof of parsing.
Checksums reject accidental corruption; an adversary able to rewrite both cache
content and checksum is outside that trust boundary. Fresh rebuild is available.
"""

import ast
import base64
from collections.abc import MutableMapping
import hashlib
import json
import sys


def _encode(value):
    if isinstance(value, ast.AST):
        return {"node": type(value).__name__, "fields": {
            key: _encode(getattr(value, key))
            for key in (*value._fields, *value._attributes) if hasattr(value, key)}}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, bytes):
        return {"bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, complex):
        return {"complex": [value.real, value.imag]}
    if value is Ellipsis:
        return {"ellipsis": True}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("unsupported AST value")


def _decode(value):
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"bytes"}:
            return base64.b64decode(value["bytes"], validate=True)
        if set(value) == {"complex"} and len(value["complex"]) == 2:
            return complex(*value["complex"])
        if value == {"ellipsis": True}:
            return Ellipsis
        if set(value) != {"node", "fields"} or not isinstance(value["node"], str):
            raise ValueError("invalid cached AST record")
        cls = vars(ast).get(value["node"])
        fields = value["fields"]
        if (not isinstance(cls, type) or not issubclass(cls, ast.AST)
                or not isinstance(fields, dict)
                or set(fields) - set((*cls._fields, *cls._attributes))):
            raise ValueError("unknown cached AST node or fields")
        return cls(**{key: _decode(item) for key, item in fields.items()})
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("invalid cached AST scalar")


class ParseCache(MutableMapping):
    """Map (path, source SHA256) to ast.Module; optionally persist in SourceStore."""

    def __init__(self, store=None):
        self.store = store
        self.memory = {}
        self.hits = 0
        self.misses = 0
        self.corrupt = 0
        if store:
            store.db.execute("CREATE TABLE IF NOT EXISTS ast_modules "
                             "(key TEXT PRIMARY KEY, content TEXT NOT NULL, digest TEXT NOT NULL)")
            store.db.commit()

    def _key(self, key):
        path, digest = key
        return json.dumps([1, sys.implementation.cache_tag, path, digest], separators=(",", ":"))

    def __getitem__(self, key):
        if key in self.memory:
            self.hits += 1
            return self.memory[key]
        row = (self.store.db.execute("SELECT content,digest FROM ast_modules WHERE key=?",
                                    (self._key(key),)).fetchone() if self.store else None)
        if row:
            try:
                if hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
                    raise ValueError("AST cache checksum mismatch")
                result = _decode(json.loads(row[0]))
                if not isinstance(result, ast.Module):
                    raise ValueError("cache root is not a Python module")
                self.memory[key] = result
                self.hits += 1
                return result
            except (ValueError, TypeError, AttributeError, KeyError, RecursionError):
                self.corrupt += 1
        self.misses += 1
        raise KeyError(key)

    def __setitem__(self, key, value):
        if not isinstance(value, ast.Module):
            raise ValueError("only parsed modules can be cached")
        self.memory[key] = value
        if self.store:
            try:
                content = json.dumps(_encode(value), sort_keys=True, ensure_ascii=True,
                                     separators=(",", ":"), allow_nan=False)
            except (ValueError, RecursionError):
                return  # Valid but unusually deep/literal-heavy source stays memory-only.
            self.store.db.execute("INSERT OR REPLACE INTO ast_modules VALUES (?,?,?)",
                                  (self._key(key), content, hashlib.sha256(content.encode()).hexdigest()))

    def __delitem__(self, key):
        self.memory.pop(key, None)
        if self.store:
            self.store.db.execute("DELETE FROM ast_modules WHERE key=?", (self._key(key),))

    def __iter__(self):
        return iter(self.memory)

    def __len__(self):
        return len(self.memory)

    @property
    def stats(self):
        return {"parse_cache_hits": self.hits, "parse_cache_misses": self.misses,
                "parse_cache_corrupt": self.corrupt}
