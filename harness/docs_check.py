"""Python 3.8 stdlib Markdown gate and conservative actual-change selection.

No HTTP or example execution. Supported: ATX/Setext headings, fenced/inline code,
inline/image/reference links, Unicode duplicate slugs and percent encoded URLs.
Complex HTML/MDX, multiline link destinations and ambiguous Markdown fail closed
when inspected. Reverse-reference scans inspect only repository prose documents.
"""
import argparse
from bisect import bisect_right
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import unicodedata
from urllib.parse import unquote, urlsplit

MAX_BYTES = 4 * 1024 * 1024
# These are instructions/execution policy, even though their suffix is Markdown.
POLICY = {'docs/workflow.md', 'docs/harness-design.md'}
# This tracked, public source is a legitimate documentation target. It grants
# neither access to other hidden paths nor a docs-only classification for CI.
PUBLIC_HIDDEN_TARGETS = {'.github/workflows/harness.yml'}
SHA = re.compile(r'^[0-9a-f]{40}$')


class DocsError(ValueError):
    pass


def prose(name):
    if not isinstance(name, str) or not name or '\\' in name or any(ord(c) < 32 for c in name):
        return False
    parts = name.split('/')
    if any(part in ('', '.', '..') for part in parts) or parts[-1] == 'AGENTS.md' or name in POLICY:
        return False
    return name == 'README.md' or (len(parts) > 1 and parts[0] == 'docs' and name.endswith('.md'))


def classify(changes):
    """Local POSIX integers stay distinct from raw Git mode strings. Empty is full."""
    if not isinstance(changes, list) or not changes:
        return {'mode': 'full', 'reason': 'empty_or_unknown_changes', 'changes': []}
    seen = set()
    for row in changes:
        if not isinstance(row, dict) or set(row) != {'status', 'old_path', 'new_path', 'old_mode', 'new_mode'}:
            return {'mode': 'full', 'reason': 'unknown_change_record', 'changes': changes}
        status = row['status']
        old, new = row['old_path'], row['new_path']
        if status not in ('A', 'M', 'D', 'R'):
            return {'mode': 'full', 'reason': 'unknown_change_type', 'changes': changes}
        expected = {'A': (None, '100644'), 'D': ('100644', None),
                    'M': ('100644', '100644'), 'R': ('100644', '100644')}[status]
        modes = row['old_mode'], row['new_mode']
        # Workspace fingerprints already require regular files. Keep *all* their
        # permission bits here: Git normalization would hide 0600 -> 0644 edits.
        regular = lambda mode: type(mode) is int and 0 <= mode <= 0o777 and not mode & 0o111
        local = ((status == 'A' and modes[0] is None and regular(modes[1])) or
                 (status == 'D' and regular(modes[0]) and modes[1] is None) or
                 (status in ('M', 'R') and regular(modes[0]) and regular(modes[1]) and
                  modes[0] == modes[1]))
        if not local and modes != expected:
            return {'mode': 'full', 'reason': 'type_mode_or_executable_change', 'changes': changes}
        if ((status == 'A' and (old is not None or not prose(new))) or
                (status == 'D' and (new is not None or not prose(old))) or
                (status in ('M', 'R') and (not prose(old) or not prose(new))) or
                (status == 'M' and old != new) or (status == 'R' and old == new)):
            return {'mode': 'full', 'reason': 'non_prose_or_unknown_path', 'changes': changes}
        for name in {old, new} - {None}:
            if name in seen:
                return {'mode': 'full', 'reason': 'ambiguous_change_paths', 'changes': changes}
            seen.add(name)
    return {'mode': 'docs', 'reason': 'actual_regular_prose_changes', 'changes': changes}


def manifest_changes(before, after):
    changes = []
    for name in sorted(set(before) | set(after)):
        a, b = before.get(name), after.get(name)
        if (name in before and name in after and a == b and all(
                isinstance(item, dict) and type(item.get('mode')) is int and
                0 <= item['mode'] <= 0o7777 for item in (a, b))):
            continue
        # Only absence of the path denotes addition/deletion; malformed entries
        # and non-integer modes cannot masquerade as Git mode evidence.
        def mode(manifest):
            if name not in manifest:
                return None
            item = manifest[name]
            value = item.get('mode') if isinstance(item, dict) else None
            return value if type(value) is int else 'unknown'
        changes.append({'status': 'A' if name not in before else 'D' if name not in after else 'M',
                        'old_path': name if name in before else None,
                        'new_path': name if name in after else None,
                        'old_mode': mode(before), 'new_mode': mode(after)})
    return changes


def change_digest(before, after):
    return hashlib.sha256(json.dumps({'baseline': before, 'candidate': after},
                                    sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def git(root, arguments):
    return subprocess.run(['git', *arguments], cwd=str(root), check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def raw_changes(data):
    fields = data.decode('utf-8', 'strict').split('\0')
    if not fields or fields.pop() != '':
        raise DocsError('Incomplete Git change evidence.')
    result = []
    while fields:
        header = fields.pop(0).split(' ')
        if len(header) != 5 or not re.fullmatch(r':[0-7]{6}', header[0]) or not re.fullmatch(r'[0-7]{6}', header[1]):
            raise DocsError('Invalid Git mode evidence.')
        old_mode, new_mode, _, _, status = header
        old_mode = old_mode[1:]
        first = fields.pop(0)
        code = status[0]
        second = fields.pop(0) if code in ('R', 'C') else first
        result.append({'status': code, 'old_path': None if code == 'A' else first,
                       'new_path': None if code == 'D' else second,
                       'old_mode': None if old_mode == '000000' else old_mode,
                       'new_mode': None if new_mode == '000000' else new_mode})
    return result


def git_changes(root, base, head):
    if not SHA.fullmatch(base or '') or not SHA.fullmatch(head or '') or base == '0' * 40 or head == '0' * 40:
        raise DocsError('Unknown Git range; full validation required.')
    if git(root, ['rev-parse', '--is-shallow-repository']).strip() != b'false':
        raise DocsError('Shallow Git history; full validation required.')
    for sha in (base, head):
        if git(root, ['rev-parse', '--verify', sha + '^{commit}']).decode().strip() != sha:
            raise DocsError('Invalid Git commit range.')
    if (git(root, ['rev-parse', 'HEAD']).decode().strip() != head or
            git(root, ['diff', '--raw', '-z', '--no-abbrev', head, '--']) or
            git(root, ['ls-files', '--others', '--exclude-standard', '-z'])):
        raise DocsError('Candidate differs from the complete commit evidence.')
    return raw_changes(git(root, ['diff', '--raw', '-z', '--no-abbrev', '--find-renames', base, head, '--']))


def ci_selection(root, event_name, event):
    try:
        if event_name == 'pull_request':
            base, head = event['pull_request']['base']['sha'], event['pull_request']['head']['sha']
        elif event_name == 'push':
            base, head = event['before'], event['after']
        else:
            raise DocsError('Unknown event.')
        # The checkout must be the candidate, never an unrelated merge/revision.
        if git(root, ['rev-parse', 'HEAD']).decode().strip() != head:
            raise DocsError('Checkout differs from event head.')
        return classify(git_changes(root, base, head))
    except (KeyError, TypeError, ValueError, IndexError, UnicodeError, subprocess.SubprocessError, OSError):
        return {'mode': 'full', 'reason': 'unavailable_complete_git_evidence', 'changes': []}


def safe_file(root, name):
    """Pin every directory and reject links/devices; never resolve an escape."""
    parts = name.split('/')
    if not name or name.startswith('/') or '\\' in name or any(part in ('', '.', '..') for part in parts):
        raise DocsError('Unsafe local document path.')
    root = Path(root).absolute()
    fd = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in (*root.parts[1:], *parts[:-1]):
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)
    handle = os.fdopen(file_fd, 'rb')
    info = os.fstat(handle.fileno())
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        handle.close()
        raise DocsError('Local link target must be a regular file without hard links.')
    return handle


def read_document(root, name):
    with safe_file(root, name) as handle:
        if os.fstat(handle.fileno()).st_size > MAX_BYTES:
            raise DocsError('Document exceeds byte limit.')
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise DocsError('Document exceeds byte limit.')
    text = raw.decode('utf-8', 'strict')
    if '\0' in text:
        raise DocsError('NUL in document.')
    if re.search(r'(?m)^(?:<{7}|>{7})(?: |$)', text):
        raise DocsError('Possible merge conflict marker.')
    previous = ''
    for line in text.splitlines():
        if line == '=======' and not previous.strip():
            raise DocsError('Possible orphan merge conflict separator.')
        previous = line
    return text


def visible_lines(text):
    result, fence = [], None
    paragraph = False
    for number, line in enumerate(text.splitlines(), 1):
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if match:
            token = match[1]
            if fence is None:
                fence = (token[0], len(token))
            elif token[0] == fence[0] and len(token) >= fence[1] and not match[2].strip():
                fence = None
            result.append((number, ''))
            paragraph = False
            continue
        # An indented code block cannot interrupt an existing paragraph. This
        # also keeps indented soft continuations of inline code visible to the
        # span masker, instead of discarding their closing backticks.
        if fence or (not paragraph and line.startswith(('    ', '\t'))):
            result.append((number, ''))
            continue
        result.append((number, line))
        paragraph = bool(line.strip()) and not re.match(
            r'^ {0,3}(?:#{1,6}(?:[ \t]|$)|(?:=+|-+)[ \t]*$|'
            r'(?:\*[ \t]*){3,}$|(?:_[ \t]*){3,}$|(?:-[ \t]*){3,}$)', line)
    if fence:
        raise DocsError('Unclosed fenced code block.')
    return result


def code_spans(text):
    """CommonMark backtick runs; escapes apply outside, never inside a span."""
    runs = {}
    for match in re.finditer(r'`+', text):
        runs.setdefault(len(match[0]), []).append(match.start())
    position = 0
    while position < len(text):
        if text[position] == '\\' and position + 1 < len(text) and text[position + 1] in r'!"#$%&\'()*+,-./:;<=>?@[\]^_`{|}~':
            position += 2
        elif text[position] == '`':
            start = position
            while position < len(text) and text[position] == '`':
                position += 1
            length = position - start
            candidates = runs.get(length, [])
            following = bisect_right(candidates, start)
            if following < len(candidates):
                close = candidates[following]
                yield start, position, close, close + length
                position = close + length
        else:
            position += 1


def code_content(value):
    value = value.replace('\n', ' ')
    if value.startswith(' ') and value.endswith(' ') and value.strip(' '):
        value = value[1:-1]
    return value


def mask_code(lines):
    """Mask inline spans across soft line breaks, retaining source coordinates.

    Blank/code-block lines and new block starts terminate inline parsing. A code
    opener in one paragraph must never hide a link in another block.
    """
    def masked(block):
        text = '\n'.join(line for _, line in block)
        chars = list(text)
        for start, _, _, end in code_spans(text):
            for index in range(start, end):
                if chars[index] != '\n':
                    # A code span occupies inline text, not definition-leading
                    # whitespace. Preserve that distinction after masking.
                    chars[index] = 'x'
        return [(number, line) for (number, _), line in zip(block, ''.join(chars).split('\n'))]
    block = []
    quoted = False
    for number, line in lines:
        isolated = (not line.strip() or re.match(
            r'^ {0,3}(?:#{1,6}(?:[ \t]|$)|(?:=+|-+)[ \t]*$|'
            r'(?:\*[ \t]*){3,}$|(?:_[ \t]*){3,}$|(?:-[ \t]*){3,}$)', line))
        quote = bool(re.match(r'^ {0,3}>', line))
        start = (re.match(r'^ {0,3}(?:[-+*]|[0-9]{1,9}[.)])[ \t]+', line) or
                 (quote and not quoted))
        if isolated or start:
            if block:
                yield from masked(block)
                block = []
        if isolated:
            yield from masked([(number, line)])
        else:
            block.append((number, line))
        quoted = quote
    if block:
        yield from masked(block)


def inline_text(text):
    # Code contributes its text to heading slugs; links contribute their labels.
    parts, values, position = [], [], 0
    for start, content, close, end in code_spans(text):
        parts.extend((text[position:start], '\0' + str(len(values)) + '\0'))
        values.append(code_content(text[content:close]))
        position = end
    text = ''.join(parts) + text[position:]
    text = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'<[^>]*>', '', text)
    text = re.sub(r'\\([!"#$%&\'()*+,\-./:;<=>?@\[\]\\^_`{|}~])', r'\1', text)
    text = html.unescape(text)
    return re.sub(r'\x00([0-9]+)\x00', lambda m: values[int(m[1])], text)


def slug(text):
    value = inline_text(text).strip().lower()
    return ''.join('-' if c.isspace() else c for c in value
                   if c.isspace() or c in ('-', '_') or unicodedata.category(c)[0] in ('L', 'N', 'M'))


def anchors(lines):
    found, counts, used = set(), {}, set()
    for index, (_, line) in enumerate(lines):
        match = re.match(r'^ {0,3}#{1,6}[ \t]+(.*?)(?:[ \t]+#+[ \t]*)?$', line)
        heading = match[1] if match else None
        if heading is None and index and re.fullmatch(r' {0,3}(?:=+|-+)[ \t]*', line):
            heading = lines[index - 1][1].strip()
        if heading is not None:
            base = slug(heading)
            count = counts.get(base, 0)
            candidate = base if not count else base + '-' + str(count)
            while candidate in used:
                count += 1
                candidate = base + '-' + str(count)
            counts[base] = count + 1
            used.add(candidate)
            found.add(candidate)
        for match in re.finditer(r'<(?:a|h[1-6])\b[^>]*\b(?:id|name)=["\']([^"\']+)["\'][^>]*>', line, re.I):
            found.add(html.unescape(match[1]))
    return found


def destination(value):
    value = value.strip()
    if value.startswith('<'):
        end = value.find('>')
        if end < 0:
            raise DocsError('Unclosed link destination.')
        target, tail = value[1:end], value[end + 1:].strip()
    else:
        # Parenthesized destinations support balanced parentheses via link parser.
        match = re.fullmatch(r'(\S+?)(?:\s+(".*"|\'.*\'|\(.*\)))?', value)
        if not match:
            raise DocsError('Unsupported link destination.')
        target, tail = match[1], match[2] or ''
    if tail and not re.fullmatch(r'"[^"\n]*"|\'[^\'\n]*\'|\([^\n]*\)', tail):
        raise DocsError('Unsupported link title.')
    return markdown_unescape(html.unescape(target))


def markdown_unescape(value):
    return re.sub(r'\\([!"#$%&\'()*+,\-./:;<=>?@\[\]\\^_`{|}~ ])', r'\1', value)


def links(lines, strict=True):
    definitions, body = {}, []
    normalize = lambda label: ' '.join(label.split()).casefold()
    for number, line in mask_code(lines):
        match = re.match(r'^ {0,3}\[([^\]]+)\]:\s*(.+)$', line)
        if match:
            key = normalize(match[1])
            if key in definitions:
                raise DocsError('Duplicate reference definition.')
            definitions[key] = destination(match[2])
            # Definitions can also contain broken local destinations when unused.
            yield number, definitions[key]
        else:
            body.append((number, line))
    for number, line in body:
        if strict and (re.search(r'<(?:img|a)\b[^>]*\b(?:src|href)\s*=', line, re.I) or '<!--' in line or '{#' in line):
            raise DocsError('Unsupported HTML/comment/custom-anchor syntax; review and full validation required.')
        if not strict:
            for tag in re.finditer(r'<(?:img|a)\b[^>]*\b(?:src|href)=["\']([^"\']+)["\'][^>]*>', line, re.I):
                yield number, html.unescape(tag[1])
        position = 0
        while position < len(line):
            match = re.search(r'(?<!\\)!?\[', line[position:])
            if not match:
                break
            start = position + match.end()
            end, depth = start, 1
            while end < len(line) and depth:
                if line[end] == '\\':
                    end += 2
                    continue
                if line[end] == '[':
                    depth += 1
                elif line[end] == ']':
                    depth -= 1
                end += 1
            if depth:
                if strict:
                    raise DocsError('Unclosed/multiline link label.')
                break
            label = line[start:end - 1]
            if '[' in label:
                yield from links([(number, label)], strict=strict)
            if end < len(line) and line[end] == '(':
                start, cursor, depth = end + 1, end + 1, 1
                while cursor < len(line) and depth:
                    char = line[cursor]
                    if char == '\\':
                        cursor += 2
                        continue
                    if char == '(':
                        depth += 1
                    elif char == ')':
                        depth -= 1
                    cursor += 1
                if depth:
                    raise DocsError('Unclosed/multiline inline link.')
                yield number, destination(line[start:cursor - 1])
                position = cursor
            elif end < len(line) and line[end] == '[':
                close = line.find(']', end + 1)
                if close < 0:
                    raise DocsError('Unclosed reference link.')
                key = normalize(line[end + 1:close] or label)
                if key not in definitions:
                    raise DocsError('Undefined reference link.')
                yield number, definitions[key]
                position = close + 1
            else:
                key = normalize(label)
                if key in definitions:
                    yield number, definitions[key]
                position = end


def local_target(source, target):
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme.lower() in ('http', 'https', 'mailto', 'tel') or target.startswith('//'):
            return None
        raise DocsError('Unsupported link scheme.')
    path = unquote(parsed.path, encoding='utf-8', errors='strict')
    fragment = unquote(parsed.fragment, encoding='utf-8', errors='strict')
    if '\\' in path or '\0' in path or path.startswith('/'):
        raise DocsError('Unsafe or root-relative local link.')
    pieces = list(PurePosixPath(source).parent.parts)
    for part in path.split('/') if path else []:
        if part == '..':
            if not pieces:
                raise DocsError('Local link escapes repository.')
            pieces.pop()
        elif part not in ('', '.'):
            pieces.append(part)
    name = '/'.join(pieces) if path else source
    return name, fragment


def document_names(root):
    """Public docs/policy references only; never scan runtime/credential roots."""
    for name in ('README.md', 'AGENTS.md'):
        if (root / name).exists() or (root / name).is_symlink():
            yield name
    docs = root / 'docs'
    if docs.is_symlink():
        raise DocsError('Symlinked documentation root.')
    for directory, dirs, files in os.walk(str(docs), followlinks=False):
        if any((Path(directory) / name).is_symlink() for name in dirs):
            raise DocsError('Symlink in documentation tree.')
        for name in sorted(files):
            if name.endswith('.md'):
                yield (Path(directory) / name).relative_to(root).as_posix()


def check(root, changes):
    root = Path(root).absolute()
    selection = classify(changes)
    group = {'runner': 'docs', 'selected': 0, 'passed': 0, 'skipped': [], 'failures': [], 'errors': []}
    if selection['mode'] != 'docs':
        group.update(status='failed', errors=[{'exception_type': 'ValueError', 'reason': selection['reason']}])
        return {'status': 'failed', 'checks': {'docs': group}, 'selection': selection}
    affected = {row[key] for row in changes for key in ('old_path', 'new_path') if row[key]}
    changed_current = {row['new_path'] for row in changes if row['new_path']}
    # The complete change evidence and reverse-reference scan are a selected
    # structural assertion even for a deletion with no surviving references.
    group.update(selected=1, passed=1)
    targets, parsed = {}, {}
    def parse(name):
        if name not in parsed:
            lines = visible_lines(read_document(root, name))
            parsed[name] = (anchors(lines), list(links(lines)))
        return parsed[name]
    def validate(source, target):
        resolved = local_target(source, target)
        if resolved is None:
            return
        name, fragment = resolved
        # Explicit deny boundary even for a link: never read credential/runtime,
        # hidden config or arbitrary absolute paths. Existence uses nofollow fd.
        parts = name.split('/')
        if (name not in PUBLIC_HIDDEN_TARGETS and any(p.startswith('.') for p in parts)) or any(
                p in ('logs', 'node_modules', '__pycache__') for p in parts):
            raise DocsError('Link target crosses a private/generated boundary.')
        with safe_file(root, name):
            pass
        if fragment:
            if not name.endswith('.md'):
                raise DocsError('Unsupported fragment target type.')
            if name not in targets:
                targets[name] = anchors(visible_lines(read_document(root, name)))
            if fragment not in targets[name]:
                raise DocsError('Missing local heading fragment.')
    # Changed documents get complete validation. Surviving documents get only
    # references to changed/deleted/renamed targets; unrelated old links ignored.
    try:
        names = sorted(set(document_names(root)) | changed_current)
    except (OSError, ValueError) as exc:
        names = sorted(changed_current)
        group['errors'].append({'exception_type': 'ValueError', 'reason': str(exc)})
    for name in names:
        complete = name in changed_current
        relevant = []
        try:
            if complete:
                _, references = parse(name)
            else:
                # Only potential reverse references require syntax inspection.
                # A basename prefilter is conservative across relative paths and
                # percent encoding; unrelated historical syntax is not a gate.
                with safe_file(root, name) as handle:
                    raw = handle.read(MAX_BYTES + 1)
                decoded = unquote(markdown_unescape(html.unescape(raw.decode('utf-8', 'replace'))))
                if not any(PurePosixPath(target).name in decoded for target in affected):
                    continue
                text = raw.decode('utf-8', 'strict')
                if len(raw) > MAX_BYTES:
                    raise DocsError('Potential reverse reference exceeds byte limit.')
                # A potential affected reference in unsupported/multiline syntax
                # must not disappear from the scan and manufacture a green gate.
                references = list(links(visible_lines(text)))
            for line, target in references:
                resolved = local_target(name, target)
                if complete or (resolved and resolved[0] in affected):
                    relevant.append((line, target))
            if not complete and not relevant:
                continue
            group['selected'] += 1
            errors = []
            for line, target in relevant:
                try:
                    validate(name, target)
                except (OSError, UnicodeError, ValueError):
                    errors.append({'file': name, 'line': line, 'exception_type': 'ValueError',
                                   'reason': 'Invalid or unsupported local link/fragment.'})
            if errors:
                group['failures'].extend(errors)
            else:
                group['passed'] += 1
        except (OSError, UnicodeError, ValueError) as exc:
            # Reverse scans cannot silently ignore unparseable documents: they
            # may reference an affected target. Record bounded path/metadata only.
            group['selected'] += 1
            group['errors'].append({'file': name, 'line': 1, 'exception_type': 'ValueError',
                                    'reason': 'Document cannot be safely parsed.'})
    group['status'] = 'passed' if group['selected'] > 0 and group['passed'] == group['selected'] and not group['errors'] and not group['failures'] else 'failed'
    return {'status': group['status'], 'checks': {'docs': group}, 'selection': selection}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ci', action='store_true')
    parser.add_argument('--selection-file', type=Path)
    parser.add_argument('--base')
    parser.add_argument('--head')
    parser.add_argument('--changes-file', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    root = Path(__file__).absolute().parents[1]
    try:
        if args.ci:
            # Event data is parsed as JSON, never interpolated into shell code.
            with open(os.environ['GITHUB_EVENT_PATH'], encoding='utf-8') as handle:
                selection = ci_selection(root, os.environ.get('GITHUB_EVENT_NAME'), json.load(handle))
            if args.selection_file:
                args.selection_file.write_text(json.dumps(selection), encoding='utf-8')
            if os.environ.get('GITHUB_OUTPUT'):
                with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as handle:
                    handle.write('docs_only=' + ('true' if selection['mode'] == 'docs' else 'false') + '\n')
            print(json.dumps(selection))
            return 0
        if args.changes_file:
            selection = json.loads(args.changes_file.read_text(encoding='utf-8'))
            changes = selection['changes']
        elif args.base and args.head:
            changes = git_changes(root, args.base, args.head)
        else:
            # No guessed baseline or file-list claim can grant a docs shortcut.
            raise DocsError('Supply complete --base/--head or a trusted --changes-file.')
        report = check(root, changes)
        if args.report:
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report['status'] == 'passed' else 1
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
        print(json.dumps({'status': 'failed', 'reason': 'documentation_evidence_unavailable'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
