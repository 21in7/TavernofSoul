"""Lossless workflow prompt builders; no model or workspace I/O."""
import json

DOCUMENTATION_GUIDANCE = (
    'Assess documentation impact at task start and in every review. Changes to structure, '
    'responsibilities, data contracts, isolation, validation, failure recovery or GitHub publication '
    'policy require updates to the relevant design/boundary documents; major decisions require a new '
    'or replacement ADR. Use docs/harness-design.md, docs/adr/README.md and docs/workflow.md only '
    'when explicitly approved for reading. A typo or local behavior-preserving change may need no '
    'documentation update, but the review must record a concrete reason. Never automatically copy, '
    'read or create documents outside the approved scope. If a required document is out of scope, '
    'report its exact missing path; the reviewer must request changes with a finding attributed to '
    'an existing approved file. The main coordinator must confirm scope and prepare a new run; '
    'repair rounds do not expand approval. Documentation completeness is a semantic reviewer '
    'judgment, not something proven by a Markdown extension check.'
)


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def request_assignment(request, assigned):
    text = 'Original request:\n' + request + '\n'
    if assigned != request:
        text += 'Assigned task:\n' + assigned + '\n'
    return text


def readable_scope(readable, edit_files=None):
    if edit_files is not None and list(readable) == list(edit_files):
        return '\nApproved readable files: the exact allowed edit files listed above.'
    return '\nApproved readable files (exact paths): ' + compact(readable)


def latest_implementations(agents, task_ids):
    """Select latest explicit task IDs; unknown/legacy results stay independent.

    Original agents, repairs and events remain the full audit trail. Do not infer
    task identity from roles, response text, missing IDs or malformed IDs.
    """
    known = set(task_ids)
    results = [agent for agent in agents if agent['phase'] == 'implement']

    def identity(agent):
        value = agent.get('task_id')
        if type(value) is int and value in known:
            return value
        return None

    latest = {identity(agent): index for index, agent in enumerate(results)
              if identity(agent) is not None}
    return [{**({'task_id': agent['task_id']} if 'task_id' in agent else {}),
             'response': agent['response']}
            for index, agent in enumerate(results)
            if identity(agent) is None or latest[identity(agent)] == index]


def plan(task, owners):
    prompt = ('Plan this development task without editing files or running checks. '
              'Return ONLY JSON: {{"tasks":[{{"role":"parser","task":"...","files":["..."]}}]}}. '
              'Use each declared file exactly once; never invent additional files. '
              'Role must equal the supplied owner. Tasks execute sequentially in listed order. '
              'Do not call agent-run or harness.workflow.\nOwners: {}\nTask: {}').format(
                  compact(owners), task)
    prompt += '\n' + DOCUMENTATION_GUIDANCE
    return prompt


def implement(task, assigned, read_only, feedback):
    prompt = ('{}'
              'Allowed edit files (exact paths): {}\n'
              'Preserve existing user edits. {} '
              'Do not run checks, agent-run, harness.workflow, cron or operating data pipelines. '
              'The orchestrator runs checks. Report your result and remaining concerns.\n{}').format(
                  request_assignment(task, assigned['task']), compact(assigned['files']),
                  'Do not edit any files; this is analysis only.' if read_only else
                  'Implement the assigned change only in the allowed files.', feedback)
    prompt += '\n' + DOCUMENTATION_GUIDANCE
    return prompt


def review(task, read_only, summaries, diff, changes):
    prompt = ('Review the task outcome and candidate source against the original request. '
              'Return ONLY JSON with exactly verdict, summary, findings, documentation. '
              'verdict is approved or changes_requested. approved requires findings=[]. '
              'Otherwise each finding has file (one of the scoped files), severity '
              '(high/medium/low) and message. Inspect source as needed; do not edit files. '
              'documentation has exactly status, files, reason. status is updated, not_required '
              'or missing; reason is a nonempty string explaining the concrete impact judgment. '
              'files is a unique list of approved .md paths. updated requires at least one '
              'actual changed .md file and may reference only changed documents. not_required '
              'requires files=[] and a specific reason. missing requires changes_requested '
              'and nonempty findings attributed to approved files, even when the needed '
              'document itself is outside scope (name the missing path in reason/message). '
              'No changes is acceptable for an analysis request or an already satisfied request, '
              'but reject an unimplemented requested fix. Independently judge the final full diff, code and '
              'documentation afresh; prior attempts or approvals are not evidence of correctness.\nRead only: {}\n'
              'Request: {}\nImplementation results: {}\nDiff:\n{}').format(
                  read_only, task, compact(summaries), diff)
    prompt += '\nActual changed files: ' + compact(changes) + '\n' + DOCUMENTATION_GUIDANCE
    return prompt


def github(task, changes, review, validation, diff):
    prompt = ('Write a commit message and PR description for this reviewed, validated change. '
              'Return ONLY JSON with exactly commit_message, pr_title, pr_body (all strings). '
              'Describe the problem, final behavior and actual validation. Do not edit files, '
              'execute Git, call tools that publish, or request extra source. Do not invent tests. '
              'The orchestrator controls repository, branch, scope and merge policy.\n'
              'Task: {}\nChanged files: {}\nReview: {}\nLocal check results: {}\nDiff:\n{}').format(
                  task, compact(changes), compact(review),
                  compact([{'command': item['command'], 'status': item['status']}
                              for item in validation]), diff)

    return prompt


def correction(payload, recurring, changed):
    text = ('Required correction; do not run checks yourself. Diagnostics contain only approved '
            'source context or scoped reviewer findings. Unavailable/unattributed context has no '
            'known cause; conservatively inspect only your assigned files or report missing context. '
            'All originally required checks will run after a fresh review.\n' +
            compact(payload))
    if recurring:
        text += '\nThe same failure recurred.'
    if not changed:
        text += '\nThe preceding implementation attempt made no assigned source change.'
    return text


def repair_plan(original_prompt, diagnostic):
    prompt = (original_prompt + '\nTrusted plan diagnostic: ' + compact(diagnostic) +
              '\nReturn a fresh short complete valid JSON object with exactly tasks. '
              'Each task has exactly role (supplied owner), task (nonempty string), '
              'files (nonempty approved path list). Cover each supplied file once. '
              'Correctly escape task strings; avoid embedded unescaped quotes or code. '
              'No extra text. Keep the exact original owners and file scope.')
    return prompt
