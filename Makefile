.DEFAULT_GOAL := help
SHELL := /bin/bash

# ── Paths ────────────────────────────────────────────────────────────
QG_DIR   := quality-gate
CK_DIR   := cathedral-keeper
RPT_DIR  := reporting
ROOT     := $(shell pwd)

# ── Test targets ─────────────────────────────────────────────────────

.PHONY: test test-qg test-ck test-reporting report sarif clean help

test: test-qg test-ck test-reporting ## Run all test suites
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

# ── Analysis targets ─────────────────────────────────────────────────

report: ## Run QG + CK and generate HTML report
	python $(QG_DIR)/quality_gate.py --root $(ROOT) --json --report
	python $(CK_DIR)/ck.py analyze --root $(ROOT) --blast-radius --verbose
	python $(RPT_DIR)/generate_html_reports.py --root $(ROOT) --title "Quality Report"

sarif: ## Run QG and output SARIF
	python $(QG_DIR)/quality_gate.py --root $(ROOT) --sarif

# ── Utility targets ──────────────────────────────────────────────────

clean: ## Remove .quality-reports directories
	find . -type d -name ".quality-reports" -exec rm -rf {} + 2>/dev/null || true

help: ## List available targets
	@echo "KP_SDLC — Build & Quality Targets"
	@echo "──────────────────────────────────"
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
		awk -F ':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'
