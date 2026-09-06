.DEFAULT_GOAL := help
SHELL := /bin/bash

# ── Paths ────────────────────────────────────────────────────────────
QG_DIR   := quality-gate
CK_DIR   := cathedral-keeper
RPT_DIR  := reporting
INIT_DIR := sdlc-init
# fix-engine is a direct-run component (not yet in the distribution, ADR 0001).
# Its pytest suite must run in blocking CI too — closing the `fix-engine/tests`
# gap ADR 0001 explicitly earmarked for this self-CI work (E0.2).
FE_DIR   := fix-engine
# Component packages (Tier C spine): each dogfoods E1.7 and must run in the
# blocking CI suite, not just at its own PR time — the reviewer's regression-
# protection finding.
SCHEMAS_DIR := schemas
RV_DIR      := runtime-verify
EE_DIR      := eval-engine
G1_DIR      := input-gate
G2_DIR      := contract-gate
OBS_DIR     := observatory
ROOT     := $(shell pwd)

# ── Test targets ─────────────────────────────────────────────────────

.PHONY: test test-qg test-ck test-reporting test-init test-harness \
        test-schemas test-runtime-verify test-eval-engine test-input-gate \
        test-contract-gate test-observatory test-fix-engine check report sarif clean help

test: test-qg test-ck test-reporting test-init test-harness test-schemas \
      test-runtime-verify test-eval-engine test-input-gate test-contract-gate \
      test-observatory test-fix-engine ## Run all test suites
	@echo ""
	@echo "All test suites completed."

# Every suite target runs under `python -m pytest <dir>`, the single blessed
# idiom. pytest collects+runs every `test_*` regardless of a `__main__`
# self-runner (two observatory files are fixture-only, and the older per-file
# `python <file>` loop would import such a file, run ZERO tests, and exit 0 — a
# vacuous green that ships a broken component) AND exits 5 on zero collection,
# so an empty or renamed tests dir fails CLOSED too. The exact-command contract
# in harness/selfci/tests/test_makefile_ci_contract.py pins each target to its
# own dir with no failure mask; completeness (no on-disk suite left unwired) is
# derived from disk there, not from a hand-maintained list.
test-qg: ## Run Quality Gate tests
	@echo "=== Quality Gate Tests ==="
	python -m pytest $(QG_DIR)/tests/ -q

test-ck: ## Run Cathedral Keeper tests
	@echo "=== Cathedral Keeper Tests ==="
	python -m pytest $(CK_DIR)/tests/ -q

test-reporting: ## Run Reporting tests
	@echo "=== Reporting Tests ==="
	python -m pytest $(RPT_DIR)/tests/ -q

test-init: ## Run sdlc-init tests
	@echo "=== sdlc-init Tests ==="
	python -m pytest $(INIT_DIR)/tests/ -q

test-harness: ## Run harness tests (structural-floor, process, selfci)
	@echo "=== Harness Tests ==="
	python -m pytest harness/structural-floor/tests harness/process/tests harness/selfci/tests -q

test-schemas: ## Run E1.7 schemas tests
	@echo "=== Schemas (E1.7) Tests ==="
	python -m pytest $(SCHEMAS_DIR)/tests/ -q

test-runtime-verify: ## Run runtime-verify (G4) tests
	@echo "=== runtime-verify (G4) Tests ==="
	python -m pytest $(RV_DIR)/tests/ -q

test-eval-engine: ## Run eval-engine (G5) tests
	@echo "=== eval-engine (G5) Tests ==="
	python -m pytest $(EE_DIR)/tests/ -q

test-input-gate: ## Run input-gate (G1) tests
	@echo "=== input-gate (G1) Tests ==="
	python -m pytest $(G1_DIR)/tests/ -q

test-contract-gate: ## Run contract-gate (G2) tests
	@echo "=== contract-gate (G2) Tests ==="
	python -m pytest $(G2_DIR)/tests/ -q

test-observatory: ## Run Observatory tests
	@echo "=== Observatory Tests ==="
	python -m pytest $(OBS_DIR)/tests/ -q

test-fix-engine: ## Run fix-engine tests
	@echo "=== fix-engine Tests ==="
	python -m pytest $(FE_DIR)/tests/ -q

# ── Analysis targets ─────────────────────────────────────────────────

check: ## Blocking Quality Gate — the exact command self-CI runs (baseline ratchet, E0.6)
	python $(QG_DIR)/quality_gate.py --root . --mode check --baseline .quality-gate.baseline.json --json --sarif qg.sarif

report: ## Run QG + CK and generate HTML report
	python $(QG_DIR)/quality_gate.py --root $(ROOT) --json --report
	python $(CK_DIR)/ck.py analyze --root $(ROOT) --blast-radius --verbose
	python $(RPT_DIR)/generate_html_reports.py --root $(ROOT) --title "Quality Report"

sarif: ## Run QG (audit) and output SARIF
	@mkdir -p .quality-reports
	python $(QG_DIR)/quality_gate.py --root $(ROOT) --mode audit --sarif .quality-reports/qg.sarif

# ── Utility targets ──────────────────────────────────────────────────

clean: ## Remove .quality-reports directories
	find . -type d -name ".quality-reports" -exec rm -rf {} + 2>/dev/null || true

help: ## List available targets
	@echo "KP_SDLC — Build & Quality Targets"
	@echo "──────────────────────────────────"
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
		awk -F ':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'
