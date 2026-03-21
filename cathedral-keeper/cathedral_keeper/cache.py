"""Phase 3 — SQLite Graph Cache with Incremental Hashing.

Technique from code-review-graph: cache the parsed import graph in SQLite,
use SHA-256 file hashing to detect changes, only re-parse modified files.

For a 500-file codebase, this reduces re-parse time from several seconds
to <2 seconds on incremental updates (only changed files are re-parsed).

Location: .cathedral-keeper/graph.db (gitignored).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Dict, List

from cathedral_keeper.python_graph import ImportEdge


_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    hash TEXT NOT NULL,
    last_parsed TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS edges (
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    module TEXT NOT NULL,
    line INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
"""


class GraphCache:
    """SQLite-backed cache for parsed import graph.

    Stores file hashes and import edges. On each run, compares current
    file hashes against cached hashes to determine which files need
    re-parsing.
    """

    def __init__(self, db_path: str = ".cathedral-keeper/graph.db"):
        self._db_path = db_path

        # Create parent directories
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def get_stale_files(self, file_hashes: Dict[str, str]) -> List[str]:
        """Compare file hashes against cache. Return files that changed.

        Args:
            file_hashes: Dict mapping file path → current SHA-256 hash.

        Returns:
            List of file paths that are new or have a different hash.
        """
        if not file_hashes:
            return []

        stale: List[str] = []
        cursor = self._conn.cursor()

        for path, current_hash in file_hashes.items():
            cursor.execute("SELECT hash FROM files WHERE path = ?", (path,))
            row = cursor.fetchone()
            if row is None or row[0] != current_hash:
                stale.append(path)

        return sorted(stale)

    def update(self, file_path: str, file_hash: str, edges: List[ImportEdge]) -> None:
        """Update cache for a single re-parsed file.

        Upserts the file hash and replaces all edges originating from this file.

        Args:
            file_path: Relative file path.
            file_hash: SHA-256 hash of the file content.
            edges: Import edges originating from this file.
        """
        cursor = self._conn.cursor()

        # Upsert file hash
        cursor.execute(
            "INSERT OR REPLACE INTO files (path, hash, last_parsed) VALUES (?, ?, datetime('now'))",
            (file_path, file_hash),
        )

        # Replace edges for this file
        cursor.execute("DELETE FROM edges WHERE src = ?", (file_path,))
        for edge in edges:
            cursor.execute(
                "INSERT INTO edges (src, dst, module, line) VALUES (?, ?, ?, ?)",
                (edge.src_file, edge.dst_file, edge.module, edge.line),
            )

        self._conn.commit()

    def get_cached_edges(self) -> List[ImportEdge]:
        """Load the complete set of cached edges.

        Returns:
            List of ImportEdge objects from all cached files.
        """
        cursor = self._conn.cursor()
        cursor.execute("SELECT src, dst, module, line FROM edges")
        return [
            ImportEdge(src_file=row[0], dst_file=row[1], module=row[2], line=row[3])
            for row in cursor.fetchall()
        ]

    def clear(self) -> None:
        """Drop all cached data (for forced rebuild)."""
        cursor = self._conn.cursor()
        cursor.execute("DELETE FROM files")
        cursor.execute("DELETE FROM edges")
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
