"""Pure, Python 3.8 contracts for approval-gated improvement discovery.

No filesystem, environment, model, workflow or network access occurs here.
Task-2 integration contract (validators use ValidationError for contract failures):

* validate_config(parsed_json) checks exact version/keys and hard ceilings.
* validate_scope_paths(lines) accepts individual repository-relative files only.
* fingerprint_sources({path: {exists: bool, mode: int|None, content: bytes|None}})
  hashes ALL approved read dependencies, including missing files and POSIX modes.
  The caller must securely obtain snapshots; this module never opens a path.
* validate_candidates({"candidates": [...]}, {path: UTF8_text_or_None}) validates
  one specialist response, at most two candidates. Optional allowed_files is the
  exact model scope; never pass a broader scope than that model actually saw.
  Candidate narrative ceilings are 4x CANDIDATE_DISPLAY_LIMITS; accepted prose
  keeps the established outer trim and is never shortened before review/IDs.
  The full JSON response still has the separate 64KiB byte ceiling.
* proposal_record(validated_candidate, fingerprints) creates immutable
  {id, digest, candidate, source_fingerprints}; digest covers all four inputs
  (schema version, candidate, dependency contents/modes/existence). Store human
  decisions/approvals, workflow claims and delivery state SEPARATELY. Rediscovery
  must reuse identity without replacing those records. IDs are not authority.
* validate_review({reviews: [...], documentation: {...}}, proposals, allowed_files)
  requires exactly one independent verdict per proposal. A missing/failed review
  must remain visibly incomplete; the caller must never synthesize eligibility.
  Review reasons and per-candidate/global documentation reasons retain up to
  1440 characters with private=True; public consumers explicitly pass
  private=False for the original 360 bound.
* build_web_report(report) projects a PRIVATE immutable report into the public
  improvement-web-v1 contract. render_html/render_markdown accept that payload.
  validate_web_report(payload) checks the exact public contract and digest.
  Display projections redact/compact and visibly abbreviate with an ellipsis;
  reviewer redaction never abbreviates. Public validation keeps the original
  display maxima, even with a recomputed digest.
  Pass max_proposals=config['limits']['max_reported_proposals'] when lowered.
  Human approval text, prompts, model raw responses, logs and source are never
  read by the projection. Transport/human state must not alter report digests.

Private report input: date (KST YYYY-MM-DD), generated_at (aware ISO8601),
status (scanned|partial|failed), proposals (proposal_record entries with optional
review objects), agents (real role/provider/model/status, optional actual timing
and cost retained privately), documentation, optional headline/summary/analogy,
and optional counts={candidates, additional_candidates}. At most eight candidates
are accepted; three cards are projected. Agent status is succeeded|failed|
unavailable|not_called. Never label an attempted/failed role as succeeded.
An optional private report_window is exactly [previous 09:00, date 09:00) KST;
generated_at must follow that cutoff and successful agents need actual timestamps
inside the window. Local participation and historical reviewed_agents stay private.

Public JSON exact top-level fields: version, date, generated_at, status, headline,
summary, analogy, proposals, agents, counts, documentation, digest. proposals have
id/priority/title/analogy/issue/evidence/benefit/risk/edit_files/validation_plan/
documentation_impact/review/approval_wording. evidence={path,start_line,end_line,
summary}; benefit={kind,text,evidence}, kind=estimated|measured; review={verdict,
reason,documentation}, verdict=eligible|rejected|needs_evidence. A missing review
projects as needs_evidence and forces partial. agents contain ONLY role/provider/
model/status (null provider/model allowed for unavailable/not_called). counts has
candidates/reported/additional_candidates/eligible. documentation={status,files,
reason}, status=required|missing|not_required. These judgments are advisory plans,
not claims that documents were changed. Digest is SHA256 of UTF-8 canonical JSON
(ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False),
excluding digest itself. HTTP readback must verify this digest AND the KST date.

Authority and isolation, source snapshot safety, mode/staleness revalidation,
trusted approvals, locking, persistence, actual model metadata and HTTP delivery
belong to improvements.py. Rendering/evidence line checks prove no semantics.

Makefile CLI contract: discover [--scope-file PATH], daily [--deliver], status
[--date YYYY-MM-DD], approve --proposal-id ID --instruction-file PATH
[--local-only], reject --proposal-id ID, execute --proposal-id ID. The runtime
also accepts tick (existing Sites publisher connected), loop-status, and publish
[--reconcile] for the hourly engine. Legacy daily cannot admit models after loop
activation or replace/repost a frozen morning day. The daily
target sets TAVERN_IMPROVEMENT_UNATTENDED=1: the runtime must reject approval
and execution under that marker and all orchestration under TAVERN_WORKFLOW_CHILD.
CLI presence itself cannot establish human identity. Delivery failure belongs
in a separate delivery record (delivery_failed), not in this immutable payload.
No approval task/files override, credentials or publication settings belong here.
"""

import datetime as dt
import hashlib
import html
import json
import re
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping, Optional, Sequence

from harness import improvement_diagnostics as diagnostics


CONFIG_VERSION = "improvement-config-v1"
PROPOSAL_VERSION = "improvement-proposal-v1"
WEB_VERSION = "improvement-web-v1"
KST = dt.timezone(dt.timedelta(hours=9), "Asia/Seoul")
MAX_CANDIDATES = 8
MAX_PROPOSALS = 3
MAX_RESPONSE_BYTES = 65536
MAX_WEB_BYTES = 262144
SPECIALIST_ROLES = ("coordinator", "downloader", "parser", "django")
ROLES = SPECIALIST_ROLES + ("reviewer",)
STATUSES = ("scanned", "partial", "failed")
VERDICTS = ("eligible", "rejected", "needs_evidence")
AGENT_STATUSES = ("succeeded", "failed", "unavailable", "not_called")
LIMIT_CEILINGS = {
    "max_reported_proposals": 3,
    "max_candidates_per_specialist": 2,
    "max_role_calls": 5,
    "call_timeout_seconds": 600,
    "max_retries": 0,
    "max_scope_files": 64,
    "max_file_bytes": 131072,
    "max_source_bytes": 1572864,
    "max_context_bytes": 2097152,
    "max_response_bytes": MAX_RESPONSE_BYTES,
    "max_evidence": 6,
    "max_edit_files": 12,
    "max_validation_steps": 6,
    "approval_expiry_days": 7,
    "delivery_timeout_seconds": 30,
    "max_delivery_bytes": MAX_WEB_BYTES,
}
CANDIDATE_FIELDS = (
    "title", "priority", "analogy", "issue", "evidence", "benefit", "risk",
    "edit_files", "validation_plan", "documentation_impact",
)
# Character limits, independent of the unchanged 64KiB response byte ceiling.
# Public web-v1 limits stay fixed; retained candidate/reviewer prose gets headroom.
CANDIDATE_DISPLAY_LIMITS = {
    "title": 80, "analogy": 200, "issue": 400, "evidence_summary": 240,
    "benefit": 240, "risk": 240, "validation_step": 200,
    "documentation_impact": 360,
}
PRIVATE_PROSE_MULTIPLIER = 4
REVIEW_DISPLAY_LIMIT = 360
REVIEW_PRIVATE_LIMIT = REVIEW_DISPLAY_LIMIT * PRIVATE_PROSE_MULTIPLIER


class ValidationError(ValueError):
    """Bounded contract failure; messages never include raw model responses."""

    def __init__(self, message, *, reason=None):
        # Optional private metadata, never model values or exception text. The
        # adapters still allowlist this independently before persisting it.
        self.reason = reason if type(reason) is str and len(reason) <= 64 and reason in (
            'candidate_edit_files_invalid', 'candidate_edit_files_duplicate',
            'candidate_edit_files_outside_scope') else None
        super().__init__(message)


def _invalid(message, field, rule, reason=None):
    if field == 'edit_files' and reason is None:
        reason = 'candidate_edit_files_invalid'
    error = ValidationError(message, reason=reason)
    if field is not None:
        try:
            diagnostics.attach(error, diagnostics.detail(error.reason or 'candidate_invalid',
                'validation', phase='candidate', field=field, rule=rule))
        except (Exception, KeyboardInterrupt):
            pass  # Keep this exact validation failure if diagnostics fail.
    return error


def _object(value: Any, required: Iterable[str], optional: Iterable[str] = (), *, field=None) -> dict:
    if not isinstance(value, dict):
        raise _invalid("expected JSON object", field, 'type')
    required, optional = set(required), set(optional)
    if not required.issubset(value) or set(value) - required - optional:
        raise _invalid("missing or unknown object fields", field, 'fields')
    return value


def _text(value: Any, limit: int, *, field=None) -> str:
    if not isinstance(value, str):
        raise _invalid("empty or oversized text", field, 'type')
    if not value.strip():
        raise _invalid("empty or oversized text", field, 'empty')
    if len(value) > limit:
        raise _invalid("empty or oversized text", field, 'length')
    if any(ord(c) < 32 and c not in "\n\t\r" for c in value):
        raise _invalid("control character in text", field, 'control')
    try:
        value.encode("utf-8", "strict")
    except UnicodeError:
        raise _invalid("invalid UTF-8 text", field, 'encoding') from None
    return value.strip()


def _integer(value: Any, minimum: int, maximum: int, *, field=None) -> int:
    if type(value) is not int:
        raise _invalid("integer outside permitted range", field, 'type')
    if not minimum <= value <= maximum:
        raise _invalid("integer outside permitted range", field, 'range')
    return value


def _candidate_text(value: Any, field: str, private: bool = True, *, diagnostic_field=None) -> str:
    """Validate retained prose without shortening; keep existing outer trim."""
    limit = CANDIDATE_DISPLAY_LIMITS[field]
    return _text(value, limit * PRIVATE_PROSE_MULTIPLIER if private else limit, field=diagnostic_field)


def _list(value: Any, maximum: int, minimum: int = 0, *, field=None) -> list:
    if not isinstance(value, list):
        raise _invalid("collection outside permitted range", field, 'type')
    if not minimum <= len(value) <= maximum:
        raise _invalid("collection outside permitted range", field, 'length')
    return value


def _enum(value: Any, choices: Sequence[str], *, field=None) -> str:
    if not isinstance(value, str):
        raise _invalid("unknown enumerated value", field, 'type')
    if value not in choices:
        raise _invalid("unknown enumerated value", field, 'allowlist')
    return value


def canonical_json(value: Any) -> bytes:
    """Canonical UTF-8 JSON bytes, identical for storage, IDs and HTTP digests."""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ValidationError("not canonical JSON data") from None


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def parse_json(value: Any, max_bytes: int = MAX_RESPONSE_BYTES) -> Any:
    """Strict JSON only: reject fences, duplicate fields, NaN and trailing text."""
    _integer(max_bytes, 1, MAX_RESPONSE_BYTES)
    if isinstance(value, bytes):
        if len(value) > max_bytes:
            raise ValidationError("JSON response too large")
        try:
            value = value.decode("utf-8", "strict")
        except UnicodeError:
            raise ValidationError("JSON must be UTF-8") from None
    if not isinstance(value, str):
        raise ValidationError("JSON input must be bytes or text")
    try:
        if len(value.encode("utf-8")) > max_bytes:
            raise ValidationError("JSON response too large")
    except UnicodeError:
        raise ValidationError("invalid UTF-8 JSON") from None

    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValidationError("duplicate JSON field")
            result[key] = item
        return result

    def invalid_constant(_value):
        raise ValidationError("non-finite JSON number")

    try:
        result = json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_constant)
        canonical_json(result)
        return result
    except (ValueError, RecursionError):
        raise ValidationError("invalid JSON response") from None


def validate_path(value: Any, *, field=None) -> str:
    """Repository-relative individual file, no glob, traversal or host path."""
    original = value
    value = _text(value, 240, field=field)
    path = PurePosixPath(value)
    if (value != original or path.is_absolute() or str(path) != value or
            any(part in ("", ".", "..") or part.startswith(".") for part in value.split("/")) or
            re.search(r"[\\:*?\[\]{}\s\x00-\x1f]", value) or
            re.match(r"(?i)^(logs|keys|credentials|secrets|private)(/|$)", value)):
        raise _invalid("unsafe individual file path", field, 'path')
    return value


def validate_scope_paths(paths: Iterable[str], max_files: int = 64, *, field=None) -> list:
    _integer(max_files, 1, 64)
    if isinstance(paths, (str, bytes)):
        raise _invalid("scope must be a collection of individual paths", field, 'type')
    result = []
    for item in paths:
        if len(result) >= max_files:
            raise _invalid("too many scope files", field, 'length')
        path = validate_path(item, field=field)
        if path in result:
            raise _invalid("duplicate scope file", field, 'duplicate')
        result.append(path)
    if not result:
        raise _invalid("empty scope", field, 'empty')
    return result


def validate_config(value: Any) -> dict:
    value = _object(value, ("version", "timezone", "scope_file", "specialist_roles",
                            "reviewer_role", "shared_files", "limits"))
    if value["version"] != CONFIG_VERSION or value["timezone"] != "Asia/Seoul":
        raise ValidationError("unsupported improvement configuration")
    if value["specialist_roles"] != list(SPECIALIST_ROLES) or value["reviewer_role"] != "reviewer":
        raise ValidationError("existing specialist/reviewer roles required")
    limits = _object(value["limits"], LIMIT_CEILINGS)
    for key, ceiling in LIMIT_CEILINGS.items():
        _integer(limits[key], 0 if key == "max_retries" else 1, ceiling)
    if limits["max_role_calls"] != 5:
        raise ValidationError("one call per specialist and independent reviewer required")
    if limits["max_file_bytes"] > limits["max_source_bytes"]:
        raise ValidationError("file bound exceeds total source bound")
    if limits["max_context_bytes"] < limits["max_source_bytes"]:
        raise ValidationError("context bound must accommodate bounded source")
    shared = _list(value["shared_files"], 64, 1)
    return dict(value, scope_file=validate_path(value["scope_file"]),
                shared_files=validate_scope_paths(shared), limits=dict(limits))


def fingerprint_sources(snapshots: Mapping[str, dict]) -> dict:
    """Hash secure caller snapshots; mode is stat.S_IMODE, not stat.st_mode."""
    paths = validate_scope_paths(snapshots)
    result = {}
    total = 0
    for path in sorted(paths):
        item = _object(snapshots[path], ("exists", "mode", "content"))
        if type(item["exists"]) is not bool:
            raise ValidationError("existence must be explicit boolean")
        if not item["exists"]:
            if item["mode"] is not None or item["content"] is not None:
                raise ValidationError("missing snapshot must have no mode/content")
            result[path] = {"exists": False, "mode": None, "sha256": None, "size": 0}
            continue
        mode = _integer(item["mode"], 0, 0o7777)
        content = item["content"]
        if not isinstance(content, bytes) or len(content) > LIMIT_CEILINGS["max_file_bytes"]:
            raise ValidationError("invalid or oversized source snapshot")
        total += len(content)
        if total > LIMIT_CEILINGS["max_source_bytes"]:
            raise ValidationError("source snapshots exceed total bound")
        result[path] = {"exists": True, "mode": mode, "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest()}
    return result


def _fingerprints(value: Mapping[str, dict]) -> dict:
    paths = validate_scope_paths(value)
    result = {}
    total = 0
    for path in sorted(paths):
        item = _object(value[path], ("exists", "mode", "sha256", "size"))
        if type(item["exists"]) is not bool:
            raise ValidationError("invalid fingerprint existence")
        _integer(item["size"], 0, LIMIT_CEILINGS["max_file_bytes"])
        if item["exists"]:
            _integer(item["mode"], 0, 0o7777)
            if not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
                raise ValidationError("invalid source digest")
        elif item != {"exists": False, "mode": None, "sha256": None, "size": 0}:
            raise ValidationError("invalid missing-file fingerprint")
        total += item["size"]
        if total > LIMIT_CEILINGS["max_source_bytes"]:
            raise ValidationError("source fingerprints exceed total bound")
        result[path] = dict(item)
    return result


def _paths(value: Any, allowed: Iterable[str], maximum: int = 12,
           minimum: int = 0, *, edit_targets: bool = False) -> list:
    allowed = set(allowed)
    field = 'edit_files' if edit_targets else None
    try:
        paths = [validate_path(x, field=field) for x in _list(value, maximum, minimum, field=field)]
    except ValidationError as exc:
        if edit_targets:
            exc.reason = 'candidate_edit_files_invalid'
        raise
    if len(set(paths)) != len(paths):
        raise _invalid("duplicate or out-of-scope file", field, 'duplicate', reason=(
            'candidate_edit_files_duplicate' if edit_targets else None))
    if not set(paths).issubset(allowed):
        raise _invalid("duplicate or out-of-scope file", field, 'outside_scope', reason=(
            'candidate_edit_files_outside_scope' if edit_targets else None))
    return paths


def validate_documentation(value: Any, allowed_files: Iterable[str], private: bool = True) -> dict:
    """Retain private reasons losslessly; public callers must use private=False."""
    value = _object(value, ("status", "files", "reason"))
    status = _enum(value["status"], ("required", "missing", "not_required"))
    files = _paths(value["files"], allowed_files)
    reason = _text(value["reason"], REVIEW_PRIVATE_LIMIT if private else REVIEW_DISPLAY_LIMIT)
    if len(reason) < 12:
        raise ValidationError("documentation needs a specific explanatory reason")
    if (status == "not_required" and files) or (status != "not_required" and not files):
        raise ValidationError("documentation status/files contradict")
    if any(not path.endswith(".md") for path in files):
        raise ValidationError("documentation judgment must name Markdown files")
    return {"status": status, "files": files, "reason": reason}


def _evidence(value: Any, sources: Mapping[str, Optional[str]],
              allowed: Iterable[str], minimum: int = 1, *, field=None) -> list:
    allowed = set(allowed)
    # All nested fields are literals, never candidate keys, indices or paths.
    path_field, start_field, end_field, summary_field = {
        'evidence': ('evidence.path', 'evidence.start_line', 'evidence.end_line', 'evidence.summary'),
        'benefit.evidence': ('benefit.evidence.path', 'benefit.evidence.start_line',
                             'benefit.evidence.end_line', 'benefit.evidence.summary'),
    }.get(field, (None, None, None, None))
    result = []
    for item in _list(value, 6, minimum, field=field):
        item = _object(item, ("path", "start_line", "end_line", "summary"), field=field)
        path = validate_path(item["path"], field=path_field)
        if path not in allowed or not isinstance(sources.get(path), str):
            raise _invalid("evidence needs an available approved source", path_field,
                           'outside_scope' if path not in allowed else 'source_unavailable')
        start = _integer(item["start_line"], 1, 1000000, field=start_field)
        end = _integer(item["end_line"], start, 1000000, field=end_field)
        if end > len(sources[path].splitlines()):
            raise _invalid("evidence line range exceeds source", end_field, 'range')
        result.append({"path": path, "start_line": start, "end_line": end,
                       "summary": _candidate_text(item["summary"], "evidence_summary",
                                                  diagnostic_field=summary_field)})
    return result


def validate_candidate(value: Any, sources: Mapping[str, Optional[str]],
                       allowed_files: Optional[Iterable[str]] = None) -> dict:
    """Structural/line checks; reviewer assesses semantics.

    Rejections carry diagnostics.exception_detail(error) from their occurrence
    boundary. Adapters must preserve that link, not revalidate or parse messages.
    """
    value = _object(value, CANDIDATE_FIELDS, field='schema')
    allowed = validate_scope_paths(sources if allowed_files is None else allowed_files, field='scope')
    # Sources are caller-owned snapshots, never paths to open. Missing files are
    # represented by None so that evidence cannot cite invented source lines.
    total_bytes = 0
    for path in validate_scope_paths(sources, field='sources'):
        source = sources[path]
        if source is None:
            continue
        if not isinstance(source, str):
            raise _invalid("source must be UTF-8 text or missing", 'sources', 'type')
        try:
            source_size = len(source.encode("utf-8", "strict"))
        except UnicodeError:
            raise _invalid("source must be valid UTF-8", 'sources', 'encoding') from None
        total_bytes += source_size
        if source_size > LIMIT_CEILINGS["max_file_bytes"] or total_bytes > LIMIT_CEILINGS["max_source_bytes"]:
            raise _invalid("source text exceeds byte bounds", 'sources', 'byte_limit')
    title = _candidate_text(value["title"], "title", diagnostic_field='title')
    analogy = _candidate_text(value["analogy"], "analogy", diagnostic_field='analogy')
    if not re.search(r"[가-힣]", title):
        raise _invalid("title and everyday analogy must include Korean text", 'title', 'korean')
    if not re.search(r"[가-힣]", analogy):
        raise _invalid("title and everyday analogy must include Korean text", 'analogy', 'korean')
    edit_files = _paths(value["edit_files"], allowed, minimum=1, edit_targets=True)
    if sum(len(path) for path in edit_files) > 600:
        raise _invalid("edit file list exceeds one-page character budget", 'edit_files', 'length')
    benefit = _object(value["benefit"], ("kind", "text", "evidence"), field='benefit')
    kind = _enum(benefit["kind"], ("estimated", "measured"), field='benefit.kind')
    return {
        "title": title,
        "priority": _enum(value["priority"], ("high", "medium", "low"), field='priority'),
        "analogy": analogy,
        "issue": _candidate_text(value["issue"], "issue", diagnostic_field='issue'),
        "evidence": _evidence(value["evidence"], sources, allowed, field='evidence'),
        "benefit": {"kind": kind, "text": _candidate_text(benefit["text"], "benefit", diagnostic_field='benefit.text'),
                    "evidence": _evidence(benefit["evidence"], sources, allowed,
                                          1 if kind == "measured" else 0, field='benefit.evidence')},
        "risk": _candidate_text(value["risk"], "risk", diagnostic_field='risk'),
        "edit_files": edit_files,
        "validation_plan": [_candidate_text(x, "validation_step", diagnostic_field='validation_plan')
                            for x in _list(value["validation_plan"], 6, 1, field='validation_plan')],
        "documentation_impact": _candidate_text(value["documentation_impact"], "documentation_impact",
                                                 diagnostic_field='documentation_impact'),
    }


def validate_candidates(value: Any, sources: Mapping[str, Optional[str]],
                        allowed_files: Optional[Iterable[str]] = None,
                        max_candidates: int = 2) -> list:
    value = _object(value, ("candidates",), field='schema')
    _integer(max_candidates, 1, 2)
    allowed = validate_scope_paths(sources if allowed_files is None else allowed_files, field='scope')
    result = [validate_candidate(x, sources, allowed)
              for x in _list(value["candidates"], max_candidates, field='candidates')]
    if len({digest(x) for x in result}) != len(result):
        raise _invalid("duplicate specialist candidates", 'candidates', 'duplicate')
    return result


def proposal_record(candidate: dict, source_fingerprints: Mapping[str, dict]) -> dict:
    """Only pass validate_candidate's output; this function confers no approval."""
    _object(candidate, CANDIDATE_FIELDS)
    fingerprints = _fingerprints(source_fingerprints)
    # A JSON round trip detaches mutable caller-owned structures.
    candidate = json.loads(canonical_json(candidate))
    proposal_digest = digest({"version": PROPOSAL_VERSION, "candidate": candidate,
                              "source_fingerprints": fingerprints})
    return {"id": "IMP-" + proposal_digest[:16], "digest": proposal_digest,
            "candidate": candidate, "source_fingerprints": fingerprints}


def _review_item(value: Any, allowed_files: Iterable[str], private: bool = True) -> dict:
    value = _object(value, ("verdict", "reason", "documentation"))
    documentation = validate_documentation(value["documentation"], allowed_files, private=private)
    verdict = _enum(value["verdict"], VERDICTS)
    if verdict == "eligible" and documentation["status"] == "missing":
        raise ValidationError("missing documentation cannot be eligible")
    return {"verdict": verdict, "reason": _text(
                value["reason"], REVIEW_PRIVATE_LIMIT if private else REVIEW_DISPLAY_LIMIT),
            "documentation": documentation}


def validate_review(value: Any, proposals: Sequence[dict], allowed_files: Iterable[str],
                    private: bool = True) -> dict:
    """Require exact coverage; retain private prose or enforce public bounds."""
    value = _object(value, ("reviews", "documentation"))
    allowed = validate_scope_paths(allowed_files)
    if len(proposals) > MAX_CANDIDATES:
        raise ValidationError("too many review candidates")
    expected = {x["id"]: x for x in proposals}
    if len(expected) != len(proposals):
        raise ValidationError("duplicate proposal identities")
    result, seen = [], set()
    for item in _list(value["reviews"], MAX_CANDIDATES):
        item = _object(item, ("candidate_id", "verdict", "reason", "documentation"))
        candidate_id = _text(item["candidate_id"], 20)
        if candidate_id not in expected or candidate_id in seen:
            raise ValidationError("unknown or duplicate review candidate")
        seen.add(candidate_id)
        review = _review_item({k: item[k] for k in ("verdict", "reason", "documentation")},
                              allowed, private=private)
        doc = review["documentation"]
        if review["verdict"] == "eligible" and not set(doc["files"]).issubset(
                expected[candidate_id]["candidate"]["edit_files"]):
            raise ValidationError("eligible proposal omits required document edits")
        result.append(dict(review, candidate_id=candidate_id))
    if seen != set(expected):
        raise ValidationError("incomplete independent review")
    documentation = validate_documentation(value["documentation"], allowed, private=private)
    if documentation["status"] == "missing" and any(x["verdict"] == "eligible" for x in result):
        raise ValidationError("global missing documentation contradicts eligibility")
    return {"reviews": result, "documentation": documentation}


_REDACTIONS = (
    (re.compile(r"https?://[^\s<>\"']+", re.I), "[외부 주소는 웹 보고서에서 생략했습니다]"),
    (re.compile(r"(?i)\bBearer\s+[^\s,;]+"), "[인증 정보는 웹 보고서에서 생략했습니다]"),
    (re.compile(r"(?i)\b(?:token|password|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+"), "[비공개 정보는 웹 보고서에서 생략했습니다]"),
    (re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)"), "[비공개 정보는 웹 보고서에서 생략했습니다]"),
    (re.compile(r"(?i)(?<![\w.])(?:logs|keys|credentials|secrets|private)/[^\s<>\"'`]+"), "[비공개 경로는 웹 보고서에서 생략했습니다]"),
    (re.compile(r"(?<![\w.])(?:[A-Za-z]:[\\/]|/)[^\s<>\"'`]+"), "[로컬 경로는 웹 보고서에서 생략했습니다]"),
)


def redact_text(value: str) -> str:
    """Redact accepted text for model input without display truncation."""
    _text(value, 4096)
    for pattern, replacement in _REDACTIONS:
        value = pattern.sub(replacement, value)
    return value


def safe_text(value: str, limit: int = 400) -> str:
    """Project compact redacted display text; escape HTML when rendering."""
    value = " ".join(redact_text(value).split())
    return value if len(value) <= limit else value[:limit - 1] + "…"


def _safe_documentation(value: dict) -> dict:
    return {"status": value["status"], "files": list(value["files"]),
            "reason": safe_text(value["reason"], 360)}


def _safe_evidence(items: list) -> list:
    return [dict(item, summary=safe_text(item["summary"], 240)) for item in items]


def _safe_candidate(candidate: dict, private: bool = True) -> dict:
    """Project bounded private prose, or strictly check existing public bounds."""
    # Revalidate shape and ranges without reconstructing/storing any source text.
    # Source existence/line checks already occurred before immutable persistence.
    _object(candidate, CANDIDATE_FIELDS)
    sources = {}
    evidence = _list(candidate["evidence"], 6, 1)
    benefit = _object(candidate["benefit"], ("kind", "text", "evidence"))
    kind = _enum(benefit["kind"], ("estimated", "measured"))
    if kind == "measured" and not benefit["evidence"]:
        raise ValidationError("measured benefit needs actual cited evidence")
    for item in evidence + _list(benefit["evidence"], 6):
        _object(item, ("path", "start_line", "end_line", "summary"))
        path = validate_path(item["path"])
        _integer(item["start_line"], 1, 1000000)
        _integer(item["end_line"], item["start_line"], 1000000)
        _candidate_text(item["summary"], "evidence_summary", private)
        sources[path] = None
    paths = set(sources) | set(_paths(candidate["edit_files"], candidate["edit_files"], minimum=1))
    if sum(len(path) for path in candidate["edit_files"]) > 600:
        raise ValidationError("edit file list exceeds one-page character budget")
    # Explicit projection: never copy arbitrary keys from a private report.
    return {
        "title": safe_text(_candidate_text(candidate["title"], "title", private), 80),
        "priority": _enum(candidate["priority"], ("high", "medium", "low")),
        "analogy": safe_text(_candidate_text(candidate["analogy"], "analogy", private), 200),
        "issue": safe_text(_candidate_text(candidate["issue"], "issue", private), 400),
        "evidence": _safe_evidence(evidence),
        "benefit": {"kind": kind,
                    "text": safe_text(_candidate_text(benefit["text"], "benefit", private), 240),
                    "evidence": _safe_evidence(benefit["evidence"])},
        "risk": safe_text(_candidate_text(candidate["risk"], "risk", private), 240),
        "edit_files": _paths(candidate["edit_files"], paths, minimum=1),
        "validation_plan": [safe_text(_candidate_text(x, "validation_step", private), 200)
                            for x in _list(candidate["validation_plan"], 6, 1)],
        "documentation_impact": safe_text(_candidate_text(
            candidate["documentation_impact"], "documentation_impact", private), 360),
    }


def _report_time(date: Any, generated_at: Any) -> tuple:
    date = _text(date, 10)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValidationError("date must be YYYY-MM-DD KST")
    generated_at = _text(generated_at, 40)
    try:
        dt.date.fromisoformat(date)
        stamp = dt.datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        if stamp.utcoffset() is None or stamp.astimezone(KST).date().isoformat() != date:
            raise ValueError()
    except (ValueError, OverflowError):
        raise ValidationError("generated_at must be aware and match report KST date") from None
    return date, generated_at


def build_web_report(report: Mapping[str, Any], max_proposals: int = MAX_PROPOSALS) -> dict:
    """Sanitized immutable public payload. Call only after private report exists.

    Ignores unrelated private keys by design; never serialize the input wholesale.
    Optional actual agent timing/cost and failure reason/error_type stay private
    because web-v1 exposes only identity/status. Failed or absent participation
    forces incomplete status; private diagnostics never affect the digest.
    """
    _integer(max_proposals, 1, MAX_PROPOSALS)
    required = {"date", "generated_at", "status", "proposals", "agents", "documentation"}
    if not isinstance(report, Mapping) or not required.issubset(report):
        raise ValidationError("missing private report contract fields")
    date, generated_at = _report_time(report["date"], report["generated_at"])
    window = None
    if "report_window" in report:
        # The parent selects a completed pool. This pure boundary verifies the
        # window's date and actual participation; it never performs selection,
        # freshness I/O, delivery or any model call. Private local exploration
        # remains outside web-v1's five cloud role records.
        bounds = _object(report["report_window"], ("start", "end"))
        try:
            start, end = (dt.datetime.fromisoformat(_text(bounds[key], 40).replace("Z", "+00:00"))
                          for key in ("start", "end"))
            expected_end = dt.datetime.combine(dt.date.fromisoformat(date), dt.time(9), KST)
            if (start.utcoffset() is None or end.utcoffset() is None or
                    end != expected_end or start != expected_end - dt.timedelta(days=1) or
                    dt.datetime.fromisoformat(generated_at.replace("Z", "+00:00")) < end):
                raise ValueError()
        except (TypeError, ValueError, OverflowError):
            raise ValidationError("morning report needs the previous-to-current 09:00 KST window") from None
        window = (start, end)
    status = _enum(report["status"], STATUSES)
    records = _list(report["proposals"], MAX_CANDIDATES)
    for record in records:
        _object(record, ("id", "digest", "candidate", "source_fingerprints"), ("review",))
    agents, seen_roles = [], set()
    for item in _list(report["agents"], 5):
        if not isinstance(item, dict) or not {"role", "provider", "model", "status"}.issubset(item):
            raise ValidationError("missing actual agent participation fields")
        role = _enum(item["role"], ROLES)
        if role in seen_roles:
            raise ValidationError("duplicate model participation")
        seen_roles.add(role)
        state = _enum(item["status"], AGENT_STATUSES)
        provider, model = item.get("provider"), item.get("model")
        if item.get("stage") == "local_explorer" or provider in ("mlx-lm", "mlx-vlm"):
            raise ValidationError("local exploration is private participation, not a cloud role")
        if window is not None and state == "succeeded":
            try:
                # Existing frozen/prepared legacy journals retain their original
                # finished-time projection. New history reports use admission
                # time, stable across crash recovery and delayed settlement.
                stamp_value = (item.get('started_at', item.get('finished_at'))
                               if report.get('participation_basis') == 'admission-v1' else
                               item.get('finished_at', item.get('started_at')))
                stamp = dt.datetime.fromisoformat(_text(
                    stamp_value, 40).replace("Z", "+00:00"))
                if stamp.utcoffset() is None or not window[0] <= stamp < window[1]:
                    raise ValueError()
            except (TypeError, ValueError, OverflowError):
                raise ValidationError("successful participation must occur within the report window") from None
        if state in ("succeeded", "failed"):
            provider, model = _text(provider, 80), _text(model, 120)
        else:
            provider = _text(provider, 80) if provider is not None else None
            model = _text(model, 120) if model is not None else None
        agents.append({"role": role, "provider": safe_text(provider, 80) if provider else None,
                       "model": safe_text(model, 120) if model else None, "status": state})
    if status == "scanned" and (seen_roles != set(ROLES) or
                                any(x["status"] != "succeeded" for x in agents) or
                                report.get("review_complete") is False):
        status = "partial"
    allowed, proposals, seen_ids = set(), [], set()
    # New morning projections carry individually verified original reviews.
    # Latest participation can fail while earlier fresh eligible cards survive.
    # The parent validates these bounded private pointers against original scans.
    retained = (report.get('morning_aggregate') == 'source-read-review-v1' and
                isinstance(report.get('reviewed_source'), dict) and
                isinstance(report.get('retained_provenance'), dict) and
                set(report['retained_provenance']) == {r['id'] for r in records})
    reviewer_succeeded = (report.get("review_complete") is not False and
                          (retained or any(x["role"] == "reviewer" and x["status"] == "succeeded" for x in agents)))
    # A review response is an all-candidate decision. Losing even one verdict
    # must never leave the remaining cards executable through a partial report.
    reviews = {}
    if reviewer_succeeded:
        try:
            for record in records:
                scope = validate_scope_paths(record["source_fingerprints"])
                review = _review_item(record.get("review"), scope, private=True)
                if review["verdict"] == "eligible" and not set(review["documentation"]["files"]).issubset(
                        record["candidate"]["edit_files"]):
                    raise ValidationError("eligible card omits required document edits")
                reviews[record["id"]] = review
        except (ValidationError, KeyError, TypeError):
            reviews = {}
    review_complete = reviewer_succeeded and len(reviews) == len(records)
    if records and not review_complete and status != "failed":
        status = "partial"
    for record in records:
        verified = proposal_record(record["candidate"], record["source_fingerprints"])
        if record["digest"] != verified["digest"] or record["id"] != verified["id"]:
            raise ValidationError("proposal identity/content mismatch")
        if record["id"] in seen_ids:
            raise ValidationError("duplicate report proposal")
        seen_ids.add(record["id"])
        scope = set(verified["source_fingerprints"])
        allowed.update(scope)
        candidate = _safe_candidate(record["candidate"])
        if not set(candidate["edit_files"]).issubset(scope):
            raise ValidationError("proposal edits outside fingerprint scope")
        for item in candidate["evidence"] + candidate["benefit"]["evidence"]:
            if item["path"] not in scope or not verified["source_fingerprints"][item["path"]]["exists"]:
                raise ValidationError("evidence outside available fingerprint scope")
        if not review_complete or status == "failed":
            if status != "failed":
                status = "partial"
            review = {"verdict": "needs_evidence", "reason": "독립 검토가 완료되지 않아 실행할 수 없습니다.",
                      "documentation": {"status": "not_required", "files": [],
                                        "reason": "읽기 전용 분석 보고이며 변경이나 문서 수정은 수행하지 않았습니다."}}
        else:
            review = reviews[record["id"]]
        candidate.update({"id": record["id"], "review": {
            "verdict": review["verdict"], "reason": safe_text(review["reason"], 360),
            "documentation": _safe_documentation(review["documentation"])},
            "approval_wording": "제안 " + record["id"] + " 승인"})
        proposals.append(candidate)
    supplied_counts = report.get("counts", {})
    _object(supplied_counts, (), ("candidates", "additional_candidates"))
    candidate_count = _integer(supplied_counts.get("candidates", len(records)), len(records), MAX_CANDIDATES)
    extra = _integer(supplied_counts.get("additional_candidates", candidate_count - len(records)),
                     0, MAX_CANDIDATES)
    if extra != candidate_count - len(records):
        raise ValidationError("candidate counts contradict private report")
    proposals.sort(key=lambda x: ({"high": 0, "medium": 1, "low": 2}[x["priority"]], x["id"]))
    eligible = sum(x["review"]["verdict"] == "eligible" for x in proposals)
    # For zero-candidate reports documentation may name approved documents only
    # when caller supplies the exact approved paths in approved_files.
    allowed.update(validate_scope_paths(report["approved_files"]) if report.get("approved_files") else ())
    documentation = validate_documentation(report["documentation"], allowed, private=True)
    if documentation["status"] == "missing" and eligible:
        raise ValidationError("report documentation contradicts eligibility")
    if not records:
        default_summary = ("승인 범위 점검과 독립 검토를 마쳤으며 보고할 개선 제안이 없습니다."
                           if status == "scanned" else "점검이 끝나지 않아 개선점이 없다고 판단할 수 없습니다.")
    else:
        default_summary = "개선 후보를 정리했습니다. 모델 검토는 사용자 승인을 대신하지 않습니다."
    payload = {
        "version": WEB_VERSION, "date": date, "generated_at": generated_at, "status": status,
        "headline": safe_text(report.get("headline", "자동 점검 / 승인 전 변경 없음"), 100),
        "summary": safe_text(report.get("summary", default_summary), 400),
        "analogy": safe_text(report.get("analogy", "정비사가 점검표를 드립니다. 실제 수리는 차주의 구체적인 승인 뒤에 진행합니다."), 200),
        "proposals": proposals[:max_proposals], "agents": agents,
        "counts": {"candidates": candidate_count, "reported": min(len(proposals), max_proposals),
                   "additional_candidates": candidate_count - min(len(proposals), max_proposals),
                   "eligible": eligible},
        "documentation": _safe_documentation(documentation),
    }
    payload["digest"] = digest(payload)
    if len(canonical_json(payload)) > MAX_WEB_BYTES:
        raise ValidationError("public report exceeds delivery bound")
    return validate_web_report(payload)


def verify_web_digest(payload: Mapping[str, Any], expected_date: Optional[str] = None) -> bool:
    """Transport readback check; not a human approval or service identity proof."""
    if not isinstance(payload, dict) or payload.get("version") != WEB_VERSION:
        return False
    if expected_date is not None and payload.get("date") != expected_date:
        return False
    try:
        return payload.get("digest") == digest({k: v for k, v in payload.items() if k != "digest"})
    except ValidationError:
        return False


def validate_web_report(payload: Any) -> dict:
    """Validate exact public fields without requiring access to any source.

    Return a detached JSON copy. This is structural validation, not independent
    evidence verification, operator authentication, or permission to execute.
    """
    _object(payload, ("version", "date", "generated_at", "status", "headline", "summary",
                      "analogy", "proposals", "agents", "counts", "documentation", "digest"))
    if not verify_web_digest(payload):
        raise ValidationError("public report digest mismatch")
    if len(canonical_json(payload)) > MAX_WEB_BYTES:
        raise ValidationError("oversized public report")
    _report_time(payload["date"], payload["generated_at"])
    status = _enum(payload["status"], STATUSES)
    for field, limit in (("headline", 100), ("summary", 400), ("analogy", 200)):
        value = _text(payload[field], limit)
        if safe_text(value, limit) != value:
            raise ValidationError("unsanitized public text")
    roles = set()
    for agent in _list(payload["agents"], 5):
        _object(agent, ("role", "provider", "model", "status"))
        role = _enum(agent["role"], ROLES)
        if role in roles:
            raise ValidationError("duplicate public agent role")
        roles.add(role)
        agent_status = _enum(agent["status"], AGENT_STATUSES)
        for key, limit in (("provider", 80), ("model", 120)):
            if agent[key] is None and agent_status in ("unavailable", "not_called"):
                continue
            value = _text(agent[key], limit)
            if safe_text(value, limit) != value:
                raise ValidationError("unsanitized model identity")
    if status == "scanned" and (roles != set(ROLES) or
                                any(x["status"] != "succeeded" for x in payload["agents"])):
        raise ValidationError("completed report needs genuine complete participation")
    ids, visible_eligible = set(), 0
    cards = _list(payload["proposals"], MAX_PROPOSALS)
    for card in cards:
        _object(card, CANDIDATE_FIELDS + ("id", "review", "approval_wording"))
        proposal_id = _text(card["id"], 20)
        if not re.fullmatch(r"IMP-[0-9a-f]{16}", proposal_id) or proposal_id in ids:
            raise ValidationError("invalid or duplicate public proposal identity")
        ids.add(proposal_id)
        candidate = {key: card[key] for key in CANDIDATE_FIELDS}
        # Public input must obey web-v1 bounds BEFORE projection/redaction.
        # A valid recomputed digest cannot authorize oversized public prose.
        if _safe_candidate(candidate, private=False) != candidate:
            raise ValidationError("unsanitized public candidate")
        review_doc = _object(card["review"], ("verdict", "reason", "documentation"))["documentation"]
        doc_files = _object(review_doc, ("status", "files", "reason"))["files"]
        allowed = set(card["edit_files"]) | set(_paths(doc_files, doc_files))
        review = _review_item(card["review"], allowed, private=False)
        if safe_text(review["reason"], 360) != review["reason"] or _safe_documentation(review_doc) != review_doc:
            raise ValidationError("unsanitized public review")
        if review["verdict"] == "eligible":
            visible_eligible += 1
            # agents describe the latest attempts, which may postdate each
            # retained card's successful review. Public validation is structural;
            # only the private parent can validate original Read/provenance and
            # authorize execution. A failed report still cannot certify cards.
            if status == "failed":
                raise ValidationError("failed report cannot certify eligibility")
            if not set(review_doc["files"]).issubset(card["edit_files"]):
                raise ValidationError("eligible card omits required document edits")
        if card["approval_wording"] != "제안 " + proposal_id + " 승인":
            raise ValidationError("invalid public approval wording")
    counts = _object(payload["counts"], ("candidates", "reported", "additional_candidates", "eligible"))
    total = _integer(counts["candidates"], len(cards), MAX_CANDIDATES)
    _integer(counts["reported"], len(cards), len(cards))
    _integer(counts["additional_candidates"], total - len(cards), total - len(cards))
    _integer(counts["eligible"], visible_eligible, total)
    if status == "failed" and counts["eligible"]:
        raise ValidationError("failed report cannot certify eligibility")
    doc = _object(payload["documentation"], ("status", "files", "reason"))
    validate_documentation(doc, _paths(doc["files"], doc["files"]), private=False)
    if _safe_documentation(doc) != doc:
        raise ValidationError("unsanitized public documentation")
    if doc["status"] == "missing" and counts["eligible"]:
        raise ValidationError("public documentation contradicts eligibility")
    return json.loads(canonical_json(payload))


_STATUS_LABELS = {"scanned": "점검 완료", "partial": "일부 점검 미완료", "failed": "점검 실패"}
_VERDICT_LABELS = {"eligible": "검토 적격 · 사용자 승인 대기", "rejected": "검토 제외",
                   "needs_evidence": "추가 근거 또는 검토 필요"}
_PRIORITY_LABELS = {"high": "높음", "medium": "보통", "low": "낮음"}


def _render_payload(payload: dict) -> dict:
    """Render only a digest-checked, bounded web payload, never private records."""
    return validate_web_report(payload)


def _brief(value: str, limit: int = 150) -> str:
    return value if len(value) <= limit else value[:limit - 1] + "…"


def render_html(payload: dict) -> str:
    """Escaped Korean one-page summary; full bounded details stay in JSON."""
    payload = _render_payload(payload)
    esc = lambda x: html.escape(str(x), quote=True)
    agents = "; ".join("{role}: {provider}/{model} ({status})".format(
        **dict(a, provider=a["provider"] or "미확인", model=a["model"] or "미확인"))
                       for a in payload["agents"]) or "참여 기록 없음"
    cards = []
    for card in payload["proposals"]:
        evidence = "; ".join("{}:{}–{} {}".format(e["path"], e["start_line"], e["end_line"],
                                                   _brief(e["summary"], 65)) for e in card["evidence"][:2])
        benefit = ("측정 근거 있음" if card["benefit"]["kind"] == "measured" else "예상 · 미측정")
        cards.append('<article><h2>{id} · {priority} · {title}</h2>'
                     '<p class="analogy">{analogy}</p><p>{issue}</p>'
                     '<dl><dt>근거</dt><dd>{evidence}</dd><dt>기대 효과</dt><dd>{benefit}: {benefit_text}</dd>'
                     '<dt>위험</dt><dd>{risk}</dd><dt>변경 파일 · 정확한 목록</dt><dd>{files}</dd>'
                     '<dt>동료 검토</dt><dd>{verdict}: {reason}</dd></dl>'
                     '<p class="approval">승인 의사 표현: <strong>{approval}</strong></p></article>'.format(
                         **{k: esc(v) for k, v in {
                             "id": card["id"], "priority": _PRIORITY_LABELS[card["priority"]],
                             "title": card["title"], "analogy": _brief(card["analogy"], 120),
                             "issue": _brief(card["issue"], 150), "evidence": evidence,
                             "benefit": benefit, "benefit_text": _brief(card["benefit"]["text"], 100),
                             "risk": _brief(card["risk"], 100), "files": ", ".join(card["edit_files"]),
                             "verdict": _VERDICT_LABELS[card["review"]["verdict"]],
                             "reason": _brief(card["review"]["reason"], 110),
                             "approval": card["approval_wording"],
                         }.items()}))
    if not cards:
        cards.append('<p class="empty">{}</p>'.format(esc(
            ("점검 완료 · 확인한 범위에서 제안 없음" if payload['headline'].startswith('점검 완료') else
             "점검 완료: 보고할 제안이 없습니다.") if payload["status"] == "scanned" else
            "점검 미완료: 개선점이 없음을 의미하지 않습니다.")))
    return '''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>일일 개선 점검표</title><style>
@page {{ size: A4; margin: 10mm; }}
* {{ box-sizing: border-box; }} body {{ font: 12px/1.35 sans-serif; color: #172333;
max-width: 190mm; margin: 12px auto; padding: 8px; overflow-wrap: anywhere; }}
h1 {{ font-size: 20px; margin: 0 0 6px; }} h2 {{ font-size: 14px; margin: 0 0 5px; }}
p {{ margin: 4px 0; }} .meta, footer {{ color: #46536a; font-size: 10px; }}
article {{ border: 1px solid #b7c4d7; border-radius: 6px; padding: 8px; margin: 8px 0;
break-inside: avoid; }} .analogy {{ color: #254d7d; }} dl {{ margin: 5px 0; }}
dt {{ font-weight: bold; float: left; clear: left; width: 95px; }}
dd {{ margin-left: 100px; }} .approval {{ background: #eef4fb; padding: 4px; }}
@media print {{ body {{ font-size: 8.5px; line-height: 1.2; margin: 0; padding: 0; }}
h1 {{ font-size: 16px; }} h2 {{ font-size: 11px; }} article {{ padding: 5px; margin: 5px 0; }}
.meta, footer {{ font-size: 8px; }} p {{ margin: 3px 0; }} }}
</style></head><body><header><h1>{headline}</h1>
<p><strong>자동 점검 / 승인 전 변경 없음</strong> · {date} KST · {status}</p>
<p>{summary}</p><p>{analogy}</p><p class="meta">참여: {agents}</p></header>{cards}
<footer>추가 후보 {extra}개 · 전체 후보 {total}개 · 문서 판단: {documentation}<br>
승인은 신뢰한 메인이 구체적인 사용자 지시를 확인한 뒤 기록합니다. 이 보고서는 승인이나 실행 기록이 아닙니다.<br>
생성: {generated_at} · 상세 근거와 검증 계획은 비공개 JSON 점검표에 보관합니다.</footer>
</body></html>'''.format(headline=esc(payload["headline"]), date=esc(payload["date"]),
                        status=esc(_STATUS_LABELS[payload["status"]]), summary=esc(_brief(payload["summary"], 240)),
                        analogy=esc(payload["analogy"]), agents=esc(_brief(agents, 600)),
                        cards="".join(cards), extra=payload["counts"]["additional_candidates"],
                        total=payload["counts"]["candidates"], generated_at=esc(payload["generated_at"]),
                        documentation=esc(_brief(payload["documentation"]["reason"], 180)))


def render_markdown(payload: dict) -> str:
    """Bounded three-card Markdown, with raw HTML and link syntax escaped."""
    payload = _render_payload(payload)

    def esc(value):
        value = html.escape(str(value), quote=True)
        return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", value)

    lines = ["# " + esc(payload["headline"]), "",
             "**자동 점검 / 승인 전 변경 없음** · {} KST · {}".format(
                 esc(payload["date"]), _STATUS_LABELS[payload["status"]]), "",
             esc(_brief(payload["summary"], 240)), "", esc(payload["analogy"]), "",
             "참여: " + "; ".join(esc("{role}: {provider}/{model} ({status})".format(**a))
                                 for a in payload["agents"]), ""]
    for card in payload["proposals"]:
        evidence = "; ".join("{}:{}–{} {}".format(e["path"], e["start_line"], e["end_line"],
                                                   _brief(e["summary"], 65)) for e in card["evidence"][:2])
        lines.extend(["## {} · {} · {}".format(esc(card["id"]), _PRIORITY_LABELS[card["priority"]],
                                              esc(card["title"])), "",
                      "비유: " + esc(_brief(card["analogy"], 120)), "", esc(_brief(card["issue"], 150)), "",
                      "- 근거: " + esc(evidence),
                      "- 기대 효과 ({}): {}".format("측정 근거 있음" if card["benefit"]["kind"] == "measured" else
                                                   "예상 · 미측정", esc(_brief(card["benefit"]["text"], 100))),
                      "- 위험: " + esc(_brief(card["risk"], 100)),
                      "- 변경 파일 · 정확한 목록: " + esc(", ".join(card["edit_files"])),
                      "- 동료 검토: {} — {}".format(_VERDICT_LABELS[card["review"]["verdict"]],
                                                 esc(_brief(card["review"]["reason"], 110))), "",
                      "승인 의사 표현: **" + esc(card["approval_wording"]) + "**", ""])
    if not payload["proposals"]:
        lines.extend([("점검 완료 · 확인한 범위에서 제안 없음" if payload['headline'].startswith('점검 완료') else
                       "점검 완료: 보고할 제안이 없습니다.") if payload["status"] == "scanned" else
                      "점검 미완료: 개선점이 없음을 의미하지 않습니다.", ""])
    lines.extend(["추가 후보 {}개 · 전체 후보 {}개".format(payload["counts"]["additional_candidates"],
                                                      payload["counts"]["candidates"]), "",
                  "문서 판단: " + esc(_brief(payload["documentation"]["reason"], 180)), "",
                  "승인은 신뢰한 메인이 구체적인 사용자 지시를 확인한 뒤 기록합니다.", "",
                  "생성: " + esc(payload["generated_at"]), ""])
    return "\n".join(lines)
