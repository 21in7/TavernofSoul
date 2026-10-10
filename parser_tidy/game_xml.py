"""Strict ElementTree parsing with the engine's narrow ScriptName extension.

Only literal XML 1.0 forbidden ASCII controls in quoted ScriptName attributes
of start tags are masked. Other malformed XML still raises ET.ParseError.
The parsed attributes regain their original controls; input files are never
written. Decoding remains the caller's responsibility.
"""
import re
import xml.etree.ElementTree as ET


_CONTROLS = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f]')
_SPACE = ' \t\r\n'
# This lexer identifies attribute boundaries, not XML name validity. The
# standard parser remains responsible for validating names and all markup.
_NAME = r'''[^ \t\r\n/=<>'"]+'''
_TAG_NAME = re.compile('<' + _NAME)
_ATTRIBUTE = re.compile(
    r'[' + _SPACE + r']+(?P<name>' + _NAME + r')[' + _SPACE + r']*='
    r'[' + _SPACE + r']*(?P<quote>[\'"])(?P<value>.*?)(?P=quote)',
    re.DOTALL,
)


def _markup_end(text, start, declaration=False):
    """Return the end of markup, respecting quotes and declaration subsets."""
    quote = None
    brackets = 0
    index = start + 1
    while index < len(text):
        char = text[index]
        if quote is not None:
            if char == quote:
                quote = None
        elif declaration and text.startswith('<!--', index):
            end = text.find('-->', index + 4)
            if end < 0:
                return len(text)
            index = end + 3
            continue
        elif declaration and text.startswith('<?', index):
            end = text.find('?>', index + 2)
            if end < 0:
                return len(text)
            index = end + 2
            continue
        elif char in '\'"':
            quote = char
        elif declaration and char == '[':
            brackets += 1
        elif declaration and char == ']' and brackets:
            brackets -= 1
        elif char == '>' and not brackets:
            return index + 1
        index += 1
    return len(text)


def _mask_start_tag(tag, prefix, replacements):
    name = _TAG_NAME.match(tag)
    if name is None:
        return tag
    index = name.end()
    spans = []
    while index < len(tag):
        if tag[index:].lstrip(_SPACE) in ('>', '/>'):
            break
        attribute = _ATTRIBUTE.match(tag, index)
        if attribute is None:
            return tag  # Do not repair malformed attribute syntax.
        if attribute.group('name') == 'ScriptName':
            spans.append(attribute.span('value'))
        index = attribute.end()
    else:
        return tag  # An unterminated tag remains malformed.

    parts = []
    index = 0
    for start, end in spans:
        parts.append(tag[index:start])

        def mask(match):
            marker = '{}{}__'.format(prefix, len(replacements))
            replacements[marker] = match.group()
            return marker

        parts.append(_CONTROLS.sub(mask, tag[start:end]))
        index = end
    parts.append(tag[index:])
    return ''.join(parts)


def _mask_script_names(text, prefix):
    parts = []
    replacements = {}
    index = 0
    while index < len(text):
        start = text.find('<', index)
        if start < 0:
            parts.append(text[index:])
            break
        parts.append(text[index:start])
        terminator = None
        for opener, closer in (('<!--', '-->'), ('<![CDATA[', ']]>'), ('<?', '?>')):
            if text.startswith(opener, start):
                terminator = closer
                end = text.find(closer, start + len(opener))
                end = len(text) if end < 0 else end + len(closer)
                break
        if terminator is None:
            end = _markup_end(text, start, declaration=text.startswith('<!', start))
        tag = text[start:end]
        if not text.startswith(('<!--', '<![CDATA[', '<?', '<!', '</'), start):
            tag = _mask_start_tag(tag, prefix, replacements)
        parts.append(tag)
        index = end
    return ''.join(parts), replacements


def _marker_collision(root, replacements):
    # Character references or DTD entities can produce a marker even when its
    # literal spelling is absent from the source. Every generated marker must
    # occur exactly once in the standard parser's resulting tree.
    counts = dict.fromkeys(replacements, 0)
    for element in root.iter():
        values = [element.tag, element.text or '', element.tail or '']
        values.extend(element.attrib.keys())
        values.extend(element.attrib.values())
        for value in values:
            for marker in counts:
                counts[marker] += value.count(marker)
    return any(count != 1 for count in counts.values())


def fromstring(text):
    """Return the standard parsed root with original ScriptName values restored."""
    prefix = '__TOS_SCRIPTNAME_CONTROL__'
    while True:
        while prefix in text:
            prefix += '_'
        masked, replacements = _mask_script_names(text, prefix)
        root = ET.fromstring(masked)
        if not _marker_collision(root, replacements):
            break
        prefix += '_'
    for element in root.iter():
        if 'ScriptName' in element.attrib:
            value = element.attrib['ScriptName']
            for marker, control in replacements.items():
                value = value.replace(marker, control)
            element.attrib['ScriptName'] = value
    return root


def parse(source):
    """Parse an already decoded text stream, returning an ElementTree."""
    return ET.ElementTree(fromstring(source.read()))
