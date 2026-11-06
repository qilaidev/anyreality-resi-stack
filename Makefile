.PHONY: help lint test shellcheck shfmt ruff yamllint jsonlint mdcheck redact examples clean

SHELL := /usr/bin/env bash
REPO_ROOT := $(shell pwd)

SH_FILES := $(shell find install scripts -type f \( -name '*.sh' -o -name '*.bash' \) 2>/dev/null)
PY_FILES := subscription tests
YAML_FILES := $(shell find templates examples .github -type f \( -name '*.yml' -o -name '*.yaml' \) 2>/dev/null)
JSON_FILES := $(shell find templates examples -type f -name '*.json' 2>/dev/null)
MD_FILES := $(shell find . -type f -name '*.md' -not -path './.git/*' 2>/dev/null)

help:
	@echo "Targets:"
	@echo "  make lint        — run all linters (shellcheck/shfmt/ruff/yamllint/jsonlint)"
	@echo "  make test        — run subscription unit tests"
	@echo "  make redact      — scan tree for leaked credentials"
	@echo "  make examples    — regenerate examples/ from templates/"
	@echo "  make shellcheck  — bash static analysis"
	@echo "  make shfmt       — bash formatting check"
	@echo "  make ruff        — Python lint"
	@echo "  make yamllint    — YAML lint"
	@echo "  make jsonlint    — JSON lint"
	@echo "  make mdcheck     — markdown link check (uses markdown-link-check or npx fallback)"
	@echo "  make clean       — remove generated examples"

lint: shellcheck shfmt ruff yamllint jsonlint

test:
	@python3 -m unittest discover -s tests -p 'test_*.py'

shellcheck:
	@command -v shellcheck >/dev/null || { echo "shellcheck not installed; brew install shellcheck"; exit 1; }
	@if [[ -n "$(SH_FILES)" ]]; then shellcheck -x -S warning $(SH_FILES); fi

shfmt:
	@command -v shfmt >/dev/null || { echo "shfmt not installed; brew install shfmt"; exit 1; }
	@if [[ -n "$(SH_FILES)" ]]; then shfmt -d -i 2 -ci $(SH_FILES); fi

ruff:
	@command -v ruff >/dev/null || { echo "ruff not installed; pip install ruff==0.15.22 (version pinned in .github/workflows/lint.yml)"; exit 1; }
	@ruff check $(PY_FILES)

yamllint:
	@command -v yamllint >/dev/null || { echo "yamllint not installed; pip install yamllint"; exit 1; }
	@if [[ -n "$(YAML_FILES)" ]]; then yamllint -s $(YAML_FILES); fi

jsonlint:
	@if [[ -n "$(JSON_FILES)" ]]; then for f in $(JSON_FILES); do python3 -m json.tool < "$$f" >/dev/null || { echo "Invalid JSON: $$f"; exit 1; }; done; fi

mdcheck:
	@if command -v markdown-link-check >/dev/null 2>&1; then \
		cmd="markdown-link-check"; \
	elif command -v npx >/dev/null 2>&1; then \
		cmd="npx --yes markdown-link-check"; \
	else \
		echo "markdown-link-check not installed; install Node.js/npx or run: npm i -g markdown-link-check"; \
		exit 1; \
	fi; \
	for f in $(MD_FILES); do \
		attempt=1; \
		until $$cmd -q -c .markdown-link-check.json "$$f"; do \
			if [[ $$attempt -ge 2 ]]; then exit 1; fi; \
			echo "markdown-link-check failed for $$f; retrying once..."; \
			attempt=$$((attempt + 1)); \
			sleep 2; \
		done; \
	done

redact:
	@scripts/redact.sh

examples:
	@scripts/make-example.sh

clean:
	@rm -rf examples/single-node/* examples/dual-node/*
	@echo "Cleaned generated examples."
