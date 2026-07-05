#!/usr/bin/env bash
# kp-sdlc harness bootstrap — thin shim over the one executor.
#
# The file-map and copy logic live in sdlc-init/sdlc_init/ (a single Python
# source), consumed by both this script and `sdlc init`. This shim exists for
# backward compatibility with `bash bootstrap.sh [target]`; it runs the
# copy-only path (placeholders left for manual fill).
#
# For an end-to-end born-gated repo (placeholders filled, floor generated,
# engine pinned), use:  sdlc init --name <name> --owner <@owner> --target <dir>
#
# Usage:
#   bash <KP_SDLC>/harness/bootstrap.sh                   # bootstrap into cwd
#   bash <KP_SDLC>/harness/bootstrap.sh /path/to/project  # explicit target
set -euo pipefail

HARNESS_DIR="$( cd "$(dirname "${BASH_SOURCE[0]}")" && pwd )"
ENGINE_ROOT="$( cd "$HARNESS_DIR/.." && pwd )"
TARGET_DIR="${1:-$(pwd)}"

# Pick the first interpreter that actually runs — skips the Windows Store
# `python3` alias stub, which is on PATH but exits non-zero.
PY=""
for cand in python3 python py; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" --version >/dev/null 2>&1; then
    PY="$cand"; break
  fi
done
if [[ -z "$PY" ]]; then
  echo "error: no working Python found — the harness executor requires Python." >&2
  exit 1
fi

# Run as a module so package-relative imports resolve (vendored/checkout case;
# when installed via pip, use the `sdlc` entry point instead).
exec env PYTHONPATH="$ENGINE_ROOT/sdlc-init" "$PY" -m sdlc_init.cli bootstrap \
  --target "$TARGET_DIR" --engine-root "$ENGINE_ROOT"
