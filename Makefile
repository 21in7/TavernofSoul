PYTHON ?= $(if $(wildcard harness/.venv/bin/python),harness/.venv/bin/python,$(if $(wildcard TavernofSoul/itos/3.8/bin/python),TavernofSoul/itos/3.8/bin/python,python3))

.PHONY: help doctor check check-downloader check-parser check-django check-pipeline doctor-mysql check-mysql check-mysql-container doctor-browser check-browser check-browser-container
.PHONY: check-live check-site check-site-container

help:
	@echo "doctor          Check the offline harness environment"
	@echo "check-downloader Run local patch, failure, and retry checks"
	@echo "check-parser    Run parser regressions without game data"
	@echo "check-django    Run importer regressions and item search tests"
	@echo "check-pipeline  Parse/export a fixture, import it, and query real views"
	@echo "check           Run all required checks (fails on skipped tests)"
	@echo "doctor-mysql    Check explicit MySQL connection and test-only privileges"
	@echo "check-mysql     Run migrations, pipeline, HTTP and MySQL-specific checks"
	@echo "check-mysql-container Create a disposable MySQL container, check, and clean up"
	@echo "doctor-browser  Check pinned Playwright and launch real Chromium"
	@echo "check-browser   Run Chromium against a disposable Django fixture server"
	@echo "check-browser-container Run Chromium in Ubuntu Docker (including Ubuntu 20.04 ARM hosts)"
	@echo "check-live      Run reviewed real iTOS/kTOS samples through parser, SQLite and views"
	@echo "check-site-container Read-only Chromium smoke of the configured public sites"
	@echo "Override the interpreter with: make check PYTHON=/path/to/python"

doctor check check-downloader check-parser check-django check-pipeline doctor-mysql check-mysql doctor-browser check-browser check-live check-site:
	$(PYTHON) -m harness $@

check-mysql-container:
	bash harness/mysql.sh "$(PYTHON)"

check-browser-container:
	bash harness/browser.sh "$(PYTHON)"

check-site-container:
	bash harness/browser.sh "$(PYTHON)" check-site
