"""Turn private check results into bounded, approved-source-only repair context.

Never copy report strings into feedback. Text tracebacks are parsed locally for
location/type tokens only; even those tokens require approval and source checks.
"""
import ast
import hashlib
import json
from pathlib import Path
import re

from harness import workspace

COMMANDS = ('check', 'check-downloader', 'check-parser', 'check-django', 'check-pipeline')
EXCEPTIONS = ('AssertionError', 'TypeError', 'ValueError', 'KeyError', 'IndexError',
              'AttributeError', 'RuntimeError', 'ImportError', 'ModuleNotFoundError',
              'SyntaxError', 'NameError', 'ZeroDivisionError', 'OSError', 'TimeoutError')
CATEGORIES = ('failures', 'errors', 'skipped')
MAX_DIAGNOSTICS = 24
MAX_TEXT = 32768


def check_groups_passed(groups):
    return isinstance(groups, dict) and bool(groups) and all(
        isinstance(group, dict) and group.get('status') == 'passed' and
        type(group.get('selected')) is int and group['selected'] > 0 and
        type(group.get('passed')) is int and group['passed'] == group['selected'] and
        not group.get('skipped') and not group.get('errors') and not group.get('failures')
        for group in groups.values())


def approved_name(value, candidate, scope):
    if not isinstance(value, str) or not value or len(value) > 4096 or \
            any(char in value for char in '\r\n\0\\'):
        return None
    # Do not normalize away traversal, empty components, or dot components.
    parts = value.split('/')[1:] if value.startswith('/') else value.split('/')
    if any(part in ('.', '..', '') for part in parts):
        return None
    path = Path(value)
    if path.is_absolute():
        try:
            name = path.relative_to(Path(candidate).absolute()).as_posix()
        except ValueError:
            return None
    else:
        name = value
    if name not in scope:
        return None
    if Path(candidate).is_symlink():
        return None
    try:
        workspace.safe_path(candidate, name)
    except (ValueError, OSError):
        return None
    return name


def source_context(model_context, name, line, policy):
    if type(line) is not int or not 0 < line <= 1000000:
        return None
    try:
        if Path(model_context).is_symlink():
            return None
        path = workspace.safe_path(model_context, name)
        if not path.is_file() or path.stat().st_size > policy['max_file_bytes']:
            return None
        lines = path.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError, ValueError):
        return None
    if line > len(lines):
        return None
    context = {'file': name, 'line': line, 'context': 'available',
               'excerpt': ['{}: {}'.format(index + 1, lines[index][:240])
                           for index in range(max(0, line - 4), min(len(lines), line + 3))]}
    # Derive function names from approved source, never from node parameters or
    # a traceback's arbitrary function field. No import or execution occurs.
    try:
        source = '\n'.join(lines)
        if len(source) > 1048576:
            return context  # Excerpt remains available; function verification is bounded.
        tree = ast.parse(source)
        functions = [node for node in ast.walk(tree)
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and
                     node.lineno <= line <= node.end_lineno and
                     re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,79}', node.name)]
        if functions:
            context['function'] = max(functions, key=lambda node: node.lineno).name
    except (SyntaxError, ValueError, RecursionError):
        pass
    return context


def locations(entry):
    """Yield metadata candidates without forwarding any report-owned text."""
    if not isinstance(entry, dict):
        return
    yield entry.get('file', entry.get('path')), entry.get('line', entry.get('lineno'))
    frames = entry.get('frames', entry.get('traceback', []))
    if isinstance(frames, list):
        for frame in frames[-32:]:
            if isinstance(frame, dict):
                yield frame.get('file', frame.get('path', frame.get('filename'))), \
                    frame.get('line', frame.get('lineno'))
    for key in ('reason', 'longrepr', 'traceback'):
        value = entry.get(key)
        if not isinstance(value, str):
            continue
        for row in value[:MAX_TEXT].splitlines()[:256]:
            # Python tracebacks and pytest --tb=short location headings only.
            match = re.fullmatch(r'\s*File "([^"\n]{1,4096})", line ([0-9]{1,7})(?:, in [^\n]*)?', row)
            if not match:
                match = re.fullmatch(r'([^\s:]{1,4096}):([0-9]{1,7}):(?: in [^\n]*| [A-Za-z][^\n]*)?', row)
            if match:
                yield match[1], int(match[2])


def exception_type(entry):
    if not isinstance(entry, dict):
        return 'unavailable'
    for key in ('exception_type', 'type'):
        value = entry.get(key)
        if isinstance(value, str) and value in EXCEPTIONS:
            return value
    # Match a fixed type at an exception heading; discard the entire message.
    for key in ('reason', 'longrepr', 'traceback'):
        value = entry.get(key)
        if not isinstance(value, str):
            continue
        for row in value[:MAX_TEXT].splitlines()[:256]:
            match = re.fullmatch(r'(?:E\s+)?(' + '|'.join(EXCEPTIONS) + r')(?::.*)?', row.strip())
            if not match:
                match = re.fullmatch(r'[^\s:]{1,4096}:[0-9]{1,7}: (' + '|'.join(EXCEPTIONS) + r')(?::.*)?', row.strip())
            if match:
                return match[1]
    return 'unavailable'


def unavailable(command, category):
    return {'command': command, 'category': category, 'exception_type': 'unavailable',
            'context': 'unavailable', 'attribution': 'unattributed'}


def truncated(entry):
    if not isinstance(entry, dict):
        return False
    frames = entry.get('frames', entry.get('traceback', []))
    return (isinstance(frames, list) and len(frames) > 32) or any(
        isinstance(entry.get(key), str) and
        (len(entry[key]) > MAX_TEXT or entry[key][:MAX_TEXT].count('\n') >= 256)
        for key in ('reason', 'longrepr', 'traceback'))


def diagnostics(results, candidate, model_context, scope, policy):
    output = []
    source_cache = {}
    processed = 0
    for result in results:
        command = result.get('command')
        if command not in COMMANDS:
            command = 'unavailable'
        groups = result.get('checks')
        groups = list(groups.values()) if isinstance(groups, dict) else []
        found = False
        for group in groups[:64]:
            if not isinstance(group, dict):
                output.append(unavailable(command, 'errors'))
                found = True
                continue
            for category in CATEGORIES:
                entries = group.get(category, [])
                if not entries:
                    continue
                if not isinstance(entries, list):
                    entries = [None]
                for entry in entries[:MAX_DIAGNOSTICS]:
                    found = True
                    if processed >= MAX_DIAGNOSTICS:
                        output.append(unavailable(command, category))
                        break
                    processed += 1
                    contexts = []
                    for value, line in locations(entry):
                        name = approved_name(value, candidate, scope)
                        if name and type(line) is int:
                            key = (name, line)
                            if key not in source_cache:
                                source_cache[key] = source_context(model_context, name, line, policy)
                            context = source_cache[key]
                            if context and context not in contexts:
                                contexts.append(context)
                            if len(contexts) > 8:
                                break
                    if contexts:
                        # All approved frames can implicate separate exact tasks.
                        for context in contexts[-8:]:
                            output.append({'command': command, 'category': category,
                                           'exception_type': exception_type(entry), **context})
                        if len(contexts) > 8 or truncated(entry):
                            output.append(unavailable(command, category))
                    else:
                        output.append(unavailable(command, category))
                if len(entries) > MAX_DIAGNOSTICS:
                    output.append(unavailable(command, category))
            if not any(group.get(category) for category in CATEGORIES) and not check_groups_passed({'group': group}):
                output.append(unavailable(command, 'errors'))
                found = True
        if not found or len(groups) > 64:
            output.append(unavailable(command, 'errors'))
    unique = []
    for diagnostic in output:
        if diagnostic not in unique:
            unique.append(diagnostic)
    if len(unique) > MAX_DIAGNOSTICS:
        unique = unique[:MAX_DIAGNOSTICS - 1] + [unavailable('unavailable', 'errors')]
    return unique


def fingerprint(items):
    # Excerpts and line numbers change when surrounding code moves. Identity
    # contains only fixed metadata and verified approved file/function names.
    identities = set()
    for item in items:
        identity = {key: item[key] for key in
                    ('command', 'category', 'exception_type', 'file', 'function', 'context', 'severity')
                    if key in item}
        if 'message' in item:
            identity['finding_sha256'] = hashlib.sha256(item['message'].encode('utf-8')).hexdigest()
        identities.add(json.dumps(identity, sort_keys=True))
    return hashlib.sha256(json.dumps(sorted(identities)).encode('utf-8')).hexdigest()


def route(tasks, items):
    """Unattributed failures conservatively reach all original tasks, bounded by rounds."""
    pending = {}
    for index, task in enumerate(tasks):
        own = [item for item in items if item.get('file') in task['files'] or
               item.get('attribution') == 'unattributed']
        if own:
            pending[index] = own
    return pending
