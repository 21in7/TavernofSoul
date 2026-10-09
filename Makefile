PYTHON ?= $(if $(wildcard harness/.venv/bin/python),harness/.venv/bin/python,$(if $(wildcard TavernofSoul/itos/3.8/bin/python),TavernofSoul/itos/3.8/bin/python,python3))

.PHONY: help doctor check check-downloader check-parser check-django check-pipeline doctor-mysql check-mysql check-mysql-container doctor-browser check-browser check-browser-container
.PHONY: check-live check-site check-site-container
.PHONY: agent-doctor agent-configure agent-smoke agent-run agent-plan
.PHONY: agent-triage agent-triage-demo triage-smoke
.PHONY: compaction-doctor compaction-demo compaction-smoke check-compaction-engine
.PHONY: agent-workflow agent-workflow-plan agent-workflow-demo agent-workflow-status
.PHONY: agent-git-doctor agent-git-request agent-git-accept agent-git-resume

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
	@echo "agent-doctor    Inspect CLI login and API-key presence without model calls"
	@echo "agent-configure Register a hidden API key: PROVIDER=claude, zai or typesafe"
	@echo "agent-smoke     Verify a real model response: PROVIDER=codex, claude or zai"
	@echo "agent-plan      Show role command without running it: ROLE=parser"
	@echo "agent-run       Run a role: ROLE=parser TASK_FILE=/path/to/task.txt [WRITE=1]"
	@echo "agent-triage    Record a routing recommendation: TASK_FILE=... [FILES_FILE=...] [LIVE=1]"
	@echo "agent-triage-demo Observe a fixed Jev response without keys or network"
	@echo "triage-smoke    Verify the real TypeSafe decision API after key registration"
	@echo "compaction-doctor Inspect the pinned plugin, Claude Code and key registration"
	@echo "compaction-demo Exercise transcript pruning without keys or network"
	@echo "compaction-smoke Send only the synthetic transcript to Jev"
	@echo "check-compaction-engine Exercise compaction hooks in Claude Code's offline test engine"
	@echo "agent-workflow  Route, implement, review, verify and apply: TASK_FILE=... FILES_FILE=..."
	@echo "agent-workflow-plan Preview file ownership and stages without model requests"
	@echo "agent-workflow-demo Exercise fixture orchestration without API calls or source edits"
	@echo "agent-workflow-status Show the latest stage, role and model [RUN_ID=...]"
	@echo "agent-git-doctor Inspect GitHub delivery policy without API calls"
	@echo "agent-git-request Prepare the parent's next GitHub tool call: RUN_ID=..."
	@echo "agent-git-accept Validate a connector response: RUN_ID=... REQUEST_ID=... RESPONSE_FILE=..."
	@echo "agent-git-resume Continue an existing PR waiting for CI: RUN_ID=..."
	@echo "Override the interpreter with: make check PYTHON=/path/to/python"

doctor check check-downloader check-parser check-django check-pipeline doctor-mysql check-mysql doctor-browser check-browser check-live check-site:
	$(PYTHON) -m harness $@

check-mysql-container:
	bash harness/mysql.sh "$(PYTHON)"

check-browser-container:
	bash harness/browser.sh "$(PYTHON)"

check-site-container:
	bash harness/browser.sh "$(PYTHON)" check-site

agent-doctor:
	$(PYTHON) -m harness.agent_models doctor $(if $(PROVIDER),--provider "$(PROVIDER)")

agent-configure agent-smoke:
	$(PYTHON) -m harness.agent_models $(patsubst agent-%,%,$@) --provider "$(PROVIDER)" $(if $(filter 0,$(COMPACTION)),--no-compaction,$(if $(filter 1,$(COMPACTION)),--compaction))

agent-plan:
	$(PYTHON) -m harness.agent_models run --role "$(ROLE)" --dry-run $(if $(filter 1,$(WRITE)),--write) $(if $(filter 0,$(COMPACTION)),--no-compaction,$(if $(filter 1,$(COMPACTION)),--compaction))

agent-run:
	$(PYTHON) -m harness.agent_models run --role "$(ROLE)" --task-file "$(TASK_FILE)" $(if $(filter 1,$(WRITE)),--write) $(if $(filter 0,$(COMPACTION)),--no-compaction,$(if $(filter 1,$(COMPACTION)),--compaction))

agent-triage:
	$(PYTHON) -m harness.triage recommend --task-file "$(TASK_FILE)" $(if $(FILES_FILE),--files-file "$(FILES_FILE)") $(if $(EXPECTED_ROLE),--expected-role "$(EXPECTED_ROLE)") $(if $(filter 1,$(LIVE)),--live)

agent-triage-demo:
	$(PYTHON) -m harness.triage recommend --task-file harness/fixtures/triage/task.txt --files-file harness/fixtures/triage/files.txt --fixture-response harness/fixtures/triage/response.json --expected-role downloader

triage-smoke:
	$(PYTHON) -m harness.triage smoke --live

compaction-doctor compaction-demo compaction-smoke:
	$(PYTHON) -m harness.compaction $(patsubst compaction-%,%,$@) $(if $(filter compaction-smoke,$@),--live)

check-compaction-engine:
	$(PYTHON) -m harness.compaction engine

agent-workflow:
	$(PYTHON) -m harness.workflow run --task-file "$(TASK_FILE)" --files-file "$(FILES_FILE)" $(if $(filter 1,$(READ_ONLY)),--read-only) $(if $(filter 1,$(RULES_ONLY)),--rules-only) $(if $(filter 0,$(GIT)),--no-git)

agent-workflow-plan:
	$(PYTHON) -m harness.workflow plan --files-file "$(FILES_FILE)"

agent-workflow-demo:
	$(PYTHON) -m harness.workflow demo

agent-workflow-status:
	$(PYTHON) -m harness.workflow status $(if $(RUN_ID),--run-id "$(RUN_ID)")

agent-git-doctor:
	$(PYTHON) -m harness.git_publish doctor

agent-git-request agent-git-resume:
	$(PYTHON) -m harness.git_publish $(patsubst agent-git-%,%,$@) --run-id "$(RUN_ID)"

agent-git-accept:
	$(PYTHON) -m harness.git_publish accept --run-id "$(RUN_ID)" --request-id "$(REQUEST_ID)" --response-file "$(RESPONSE_FILE)"
