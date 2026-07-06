"""runtime-verify check packs.

This PR ships the reconciliation data pack; uniqueness/completeness and the
application packs land in later PRs against this same spine.
"""

from __future__ import annotations

from .data_reconcile import reconcile

__all__ = ["reconcile"]
