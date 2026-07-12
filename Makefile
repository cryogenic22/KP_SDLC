.DEFAULT_GOAL := help
SHELL := /bin/bash

# ── Paths ────────────────────────────────────────────────────────────
QG_DIR   := quality-gate
CK_DIR   := cathedral-keeper
RPT_DIR  := reporting
INIT_DIR := sdlc-init
# Component packages (Tier C spine): each dogfoods E1.7 and must run in the
# blocking CI suite, not just at its own PR time — the reviewer's regression-
# protection finding. Their tests are standalone-runnable via `python <file>`.
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
        test-contract-gate test-observatory check report sarif clean help

test: test-qg test-ck test-reporting test-init test-harness test-schemas \
      test-runtime-verify test-eval-engine test-input-gate test-contract-gate \
      test-observatory ## Run all test suites
	@echo ""
	@echo "All test suites completed."

test-qg: ## Run Quality Gate tests
	@echo "=== Quality Gate Tests ==="
	@passed=0; failed=0; \
	for f in $(QG_DIR)/tests/test_*.py; do \
		if python "$$f"; then \
			passed=$$((passed + 1)); \
		else \
			failed=$$((failed + 1)); \
		fi; \
	done; \
	echo ""; \
	echo "QG: $$passed passed, $$failed failed"; \
	[ "$$failed" -eq 0 ]

test-ck: ## Run Cathedral Keeper tests
	@echo "=== Cathedral Keeper Tests ==="
	@passed=0; failed=0; \
	for f in $(CK_DIR)/tests/test_*.py; do \
		if python "$$f"; then \
			passed=$$((passed + 1)); \
		else \
			failed=$$((failed + 1)); \
		fi; \
	done; \
	echo ""; \
	echo "CK: $$passed passed, $$failed failed"; \
	[ "$$failed" -eq 0 ]

test-reporting: ## Run Reporting tests
	@echo "=== Reporting Tests ==="
	@passed=0; failed=0; \
	for f in $(RPT_DIR)/tests/test_*.py; do \
		if python "$$f"; then \
			passed=$$((passed + 1)); \
		else \
			failed=$$((failed + 1)); \
		fi; \
	done; \
	echo ""; \
	echo "Reporting: $$passed passed, $$failed failed"; \
	[ "$$failed" -eq 0 ]

test-init: ## Run sdlc-init tests
	@echo "=== sdlc-init Tests ==="
	@passed=0; failed=0; \
	for f in $(INIT_DIR)/tests/test_*.py; do \
		if python "$$f"; then \
			passed=$$((passed + 1)); \
		else \
			failed=$$((failed + 1)); \
		fi; \
	done; \
	echo ""; \
	echo "sdlc-init: $$passed passed, $$failed failed"; \
	[ "$$failed" -eq 0 ]

test-harness: ## Run harness tests (structural-floor, process, selfci)
	@echo "=== Harness Tests ==="
	@passed=0; failed=0; \
	for f in harness/structural-floor/tests/test_*.py harness/process/tests/test_*.py harness/selfci/tests/test_*.py; do \
		if python "$$f"; then \
			passed=$$((passed + 1)); \
		else \
			failed=$$((failed + 1)); \
		fi; \
	done; \
	echo ""; \
	echo "Harness: $$passed passed, $$failed failed"; \
	[ "$$failed" -eq 0 ]

# The component suites run under `python -m pytest <dir>`, NOT the per-file
# `python <file>` loop the older targets use. Two of observatory's test files
# are pytest-fixture-only with no `__main__` self-runner, so `python <file>`
# would import them and run ZERO tests while exiting 0 (a vacuous green that
# ships a broken component). pytest collects+runs every test_* regardless of a
# __main__ block AND exits 5 on zero collection, so an empty/renamed tests dir
# fails closed too — vacuity is impossible.
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
