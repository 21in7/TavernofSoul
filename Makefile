PYTHON ?= $(if $(wildcard harness/.venv/bin/python),harness/.venv/bin/python,$(if $(wildcard TavernofSoul/itos/3.8/bin/python),TavernofSoul/itos/3.8/bin/python,python3))

.PHONY: help doctor check check-downloader check-parser check-django check-pipeline doctor-mysql check-mysql check-mysql-container doctor-browser check-browser check-browser-container
.PHONY: prepare-ipf-unpacker
.PHONY: check-live check-site check-site-container
.PHONY: agent-doctor agent-configure agent-smoke agent-run agent-plan
.PHONY: agent-triage agent-triage-demo triage-smoke
.PHONY: compaction-doctor compaction-demo compaction-smoke check-compaction-engine
.PHONY: agent-workflow agent-workflow-plan agent-workflow-demo agent-workflow-status
.PHONY: agent-git-doctor agent-git-request agent-git-accept agent-git-resume agent-git-cleanup
.PHONY: storage-status storage-doctor
.PHONY: check-docs archive-run
.PHONY: agent-improve agent-improve-daily agent-improve-status agent-improve-approve agent-improve-reject agent-improve-execute
.PHONY: agent-improve-tick agent-improve-loop-status agent-improve-publish
.PHONY: agent-improve-completion

# Quote each improvement argument as one literal shell word. Never evaluate it
# as shell code; the Python CLI validates IDs, paths and trusted-parent authority.
improve_quote = '$(subst ','"'"',$(1))'

help:
	@echo "doctor          Check the offline harness environment"
	@echo "storage-status  Inspect artifact/temp paths and local locks (read-only, no models)"
	@echo "storage-doctor  Check mounts/free space [PROBE=1: probe existing private directories]"
	@echo "prepare-ipf-unpacker Force a native release build directly to IPFUnpacker/ipf_unpack"
	@echo "check-downloader Run local patch, failure, and retry checks"
	@echo "check-parser    Run parser regressions without game data"
	@echo "check-django    Run importer regressions and item search tests"
	@echo "check-pipeline  Parse/export a fixture, import it, and query real views"
	@echo "check           Run all required checks (fails on skipped tests)"
	@echo "check-docs      Validate complete prose changes: BASE=... HEAD=... or CHANGES_FILE=..."
	@echo "archive-run     Resume only one terminal result archive: RUN_ID=... [KIND=workflows|checks]"
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
	@echo "agent-git-resume Continue existing CI wait or post-merge cleanup: RUN_ID=..."
	@echo "agent-git-cleanup Recheck a merged PR and resume cleanup: RUN_ID=..."
	@echo "agent-improve   Manual read-only discovery [SCOPE_FILE=explicit-approved-list]"
	@echo "agent-improve-daily Idempotent KST discovery [DELIVER=1]; never approve or execute"
	@echo "agent-improve-status Show the report [DATE=YYYY-MM-DD]"
	@echo "agent-improve-tick One hourly research step; deliver the frozen 09:00 KST report when due"
	@echo "agent-improve-loop-status Show loop budget, holds, next role and next report; no models"
	@echo "agent-improve-publish Deliver a frozen report without models [RECONCILE=1: explicit same-digest reconciliation]"
	@echo "agent-improve-approve Trusted parent only: PROPOSAL_ID=... INSTRUCTION_FILE=... [LOCAL_ONLY=1]"
	@echo "agent-improve-reject Trusted parent only: PROPOSAL_ID=..."
	@echo "agent-improve-execute Consume one exact approval: PROPOSAL_ID=..."
	@echo "agent-improve-completion Resume only completion delivery: RUN_ID=... [RECONCILE=1]"
	@echo "Override the interpreter with: make check PYTHON=/path/to/python"

prepare-ipf-unpacker:
	$(MAKE) -C IPFUnpacker/src/ipf_unpack -B release

storage-status:
	$(PYTHON) -m harness.storage status

storage-doctor:
	$(PYTHON) -m harness.storage doctor $(if $(filter 1,$(PROBE)),--probe)

check-docs:
	$(PYTHON) -m harness check-docs $(if $(BASE),--base $(call improve_quote,$(BASE))) $(if $(HEAD),--head $(call improve_quote,$(HEAD))) $(if $(CHANGES_FILE),--changes-file $(call improve_quote,$(CHANGES_FILE)))

archive-run:
	$(PYTHON) -m harness.archive --run-id $(call improve_quote,$(RUN_ID)) --kind $(call improve_quote,$(if $(KIND),$(KIND),workflows))

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

agent-git-request agent-git-resume agent-git-cleanup:
	$(PYTHON) -m harness.git_publish $(patsubst agent-git-%,%,$@) --run-id "$(RUN_ID)"

agent-git-accept:
	$(PYTHON) -m harness.git_publish accept --run-id "$(RUN_ID)" --request-id "$(REQUEST_ID)" --response-file "$(RESPONSE_FILE)"

agent-improve:
	$(PYTHON) -m harness.improvements discover $(if $(SCOPE_FILE),--scope-file $(call improve_quote,$(SCOPE_FILE)))

# The runtime must reject approve/execute under this environment marker too.
agent-improve-daily:
	TAVERN_IMPROVEMENT_UNATTENDED=1 $(PYTHON) -m harness.improvements daily $(if $(filter 1,$(DELIVER)),--deliver)

agent-improve-status:
	$(PYTHON) -m harness.improvements status $(if $(DATE),--date $(call improve_quote,$(DATE)))

# Main replaces the legacy daily scheduler with this target after validation.
# Do not schedule discover/daily alongside tick: they bypass the loop ledger.
# The CLI defaults to deliver=True and calls improvements.deliver_report only
# after releasing the improvement/project locks. No separate publish cron.
# The engine owns the <=600s tick deadline, shorter model/quota deadlines and
# durable hourly claim; do not wrap this command in an automatic retry loop.
agent-improve-tick:
	TAVERN_IMPROVEMENT_UNATTENDED=1 $(PYTHON) -m harness.improvement_loop tick

agent-improve-loop-status:
	$(PYTHON) -m harness.improvement_loop status

# Manual recovery only; unknown sends need explicit same-digest reconciliation.
agent-improve-publish:
	TAVERN_IMPROVEMENT_UNATTENDED=1 $(PYTHON) -m harness.improvement_loop publish $(if $(filter 1,$(RECONCILE)),--reconcile)

agent-improve-approve:
	$(PYTHON) -m harness.improvements approve --proposal-id $(call improve_quote,$(PROPOSAL_ID)) --instruction-file $(call improve_quote,$(INSTRUCTION_FILE)) $(if $(filter 1,$(LOCAL_ONLY)),--local-only)

agent-improve-reject:
	$(PYTHON) -m harness.improvements reject --proposal-id $(call improve_quote,$(PROPOSAL_ID))

agent-improve-execute:
	$(PYTHON) -m harness.improvements execute --proposal-id $(call improve_quote,$(PROPOSAL_ID))

agent-improve-completion:
	$(PYTHON) -m harness.improvement_completion --run-id $(call improve_quote,$(RUN_ID)) $(if $(filter 1,$(RECONCILE)),--reconcile)
