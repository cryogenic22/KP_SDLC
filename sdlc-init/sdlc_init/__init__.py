"""sdlc-init — the born-gated front door (Track A / Epic 11).

One manifest → one executor → any surface. The CLI is the first surface; a
future UI or CI re-run resolves the same InitManifest and calls the same
executor. Nothing else provisions.
"""

from .manifest import InitManifest, SDLC_INIT_VERSION

__version__ = SDLC_INIT_VERSION

__all__ = ["InitManifest", "__version__"]
