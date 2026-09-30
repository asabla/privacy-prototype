"""Deterministic credential safeguards for reviewed plain text, separate from OPF."""

import re

from backend.detector import HEURISTIC_PATTERNS


_CREDENTIAL_KEY = r'''(?P<key_quote>["']?)(?:api[_-]?key|access[_-]?token|token|password|passwd|secret)(?P=key_quote)'''
_CREDENTIAL_SHAPE = next(pattern for label, pattern in HEURISTIC_PATTERNS if label == "secret")
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)(?<!\w)" + _CREDENTIAL_KEY + r"\s*[:=]\s*"
    # Prefer closed multiline values, then cover unfinished values to the line end.
    r'''(?:"(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'|'''
    r'''(?:"(?:\\(?:[^\r\n]|(?=[\r\n]|$))|[^"\\\r\n])*(?:"|(?=[\r\n]|$))'''
    r'''|'(?:\\(?:[^\r\n]|(?=[\r\n]|$))|[^'\\\r\n])*(?:'|(?=[\r\n]|$))|[^\s,;"']+))'''
)
_CREDENTIAL_BLOCK = re.compile(
    r"(?i)^(?P<indent> *)" + _CREDENTIAL_KEY
    + r"[ \t]*:[ \t]*[|>](?:[1-9][+-]?|[+-][1-9]?)?[ \t]*(?:\#[^\r\n]*)?$"
)
_HTTP_HEADER = re.compile(
    r"(?i)^(?P<indent>[ \t]*)(?:authorization|proxy-authorization|cookie|set-cookie)"
    r"[ \t]*:[ \t]*(?P<value>.*)$"
)
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----[\s\S]*?(?:-----END (?:[A-Z]+ )?PRIVATE KEY-----|$)")
_QUOTE_PREFIX = re.compile(r"(?:[ \t]*>)+ ?")
_QUOTE_LEVEL = re.compile(r"[ \t]*> ?")


def _unquote(line: str, depth: int) -> str | None:
    for _ in range(depth):
        quote = _QUOTE_LEVEL.match(line)
        if quote is None:
            return None
        line = line[quote.end():]
    return line


def _structured_ranges(text: str):
    # Keep original offsets and CR/LF boundaries; never parse or execute pasted data.
    lines = list(re.finditer(r"([^\r\n]*)(?:\r\n|\r|\n|$)", text))
    for index, line in enumerate(lines):
        body = line[1]
        quote = _QUOTE_PREFIX.match(body)
        prefix = quote.end() if quote else 0
        depth = body[:prefix].count(">")
        content = body[prefix:]
        block = _CREDENTIAL_BLOCK.fullmatch(content)
        header = _HTTP_HEADER.fullmatch(content)
        match = block or header
        if match is None:
            continue
        parent_indent = len(match["indent"].expandtabs(8))
        end = line.end(1)
        for following in lines[index + 1:]:
            value = _unquote(following[1], depth)
            if value is None:
                break
            if not value.strip():
                if header:  # A blank line terminates a copied HTTP header section.
                    break
                continue
            indent = value[:len(value) - len(value.lstrip(" \t"))]
            if len(indent.expandtabs(8)) <= parent_indent:
                break
            end = following.end(1)
        if end > line.end(1) or (header and header["value"].strip()):
            yield line.start() + prefix + len(match["indent"]), end


def credential_ranges(text: str):
    """Yield code-point ranges; the caller merges overlap with model/manual masks."""
    for pattern in (_CREDENTIAL_SHAPE, _CREDENTIAL_ASSIGNMENT, _PRIVATE_KEY):
        for match in pattern.finditer(text):
            yield match.start(), match.end()
    yield from _structured_ranges(text)
