"""A strict-YAML-subset loader — hand-rolled, fail-closed, line-tracking.

The engine promises zero runtime dependencies (``dependencies = []`` is a
published identity claim), so overlay YAML is parsed here rather than via
PyYAML. The subset is deliberately narrow: block-style maps and lists,
str/int/float/bool/null scalars, single-quoted literals, ``|`` literal block
scalars, and ``[]`` / ``{}`` empty-collection literals. Anything richer —
anchors, aliases, tags, flow collections, multi-document streams, tab
indentation, duplicate keys — is refused with E-SYNTAX. It never
mis-parses: it either loads the narrow subset or refuses.

A dev-CI differential (test h) cross-checks this loader against
``yaml.safe_load`` over every shipped document, so the hand-rolled parser
has a mechanical oracle without importing one at runtime.
"""

from __future__ import annotations

import re
from collections import namedtuple

Token = namedtuple("Token", ["indent", "content", "lineno", "block"])

# Coerce only the tokens yaml.safe_load (YAML 1.1 core) resolves identically:
# a plain decimal (no leading zero) and a dotted float whose exponent, if any,
# carries an explicit sign. PyYAML types '1e3'/'1.5e3' as STRINGS (unsigned or
# dot-less exponents stay strings) and '010' as OCTAL 8 -- so a looser regex
# here would silently disagree with the oracle. Anything richer is refused.
_INT = re.compile(r"[+-]?(?:0|[1-9][0-9]*)$")
_FLOAT = re.compile(r"[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][+-][0-9]+)?$")
# YAML-1.1 implicit forms outside this narrow subset that safe_load would type
# as a non-string: miniyaml refuses them (E-SYNTAX) so the author quotes to
# disambiguate. The loader never silently mis-types a scalar -- it matches the
# oracle or it refuses; it never guesses.
_YAML11 = re.compile(
    r"[+-]?0[0-7]+$"                        # octal (010, 007) -> safe_load int
    r"|[+-]?0[xX][0-9a-fA-F]+$"             # hex (0x10)
    r"|[+-]?0[bB][01]+$"                    # binary (0b101)
    r"|[+-]?[0-9][0-9]*(?::[0-5]?[0-9])+$"  # sexagesimal (1:30)
    r"|(?:yes|Yes|YES|no|No|NO|on|On|ON|off|Off|OFF)$"  # YAML-1.1 booleans
    r"|[+-]?\.(?:inf|Inf|INF)$"             # +/- infinity
    r"|\.(?:nan|NaN|NAN)$"                  # not-a-number
)
_UNDERSCORE_NUM = re.compile(r"[0-9][0-9_]*(?:\.[0-9_]*)?(?:[eE][+-]?[0-9]+)?$")
_NULLS = ("", "null", "~", "Null", "NULL")
_TRUE = ("true", "True", "TRUE")
_FALSE = ("false", "False", "FALSE")
_CONSTS = {**{w: None for w in _NULLS},
           **{w: True for w in _TRUE},
           **{w: False for w in _FALSE}}
_MISSING = object()


class MiniYAMLError(Exception):
    """A document left the supported subset. Always carries code E-SYNTAX."""

    def __init__(self, message: str, line: int = 0) -> None:
        super().__init__(message)
        self.code = "E-SYNTAX"
        self.line = line
        self.message = message


def load(text: str):
    """Parse ``text`` -> (data, lines) where ``lines`` maps each node's
    tuple-path to its 1-based source line. Raises MiniYAMLError (E-SYNTAX)
    on anything outside the subset."""
    tokens = _tokenize(text)
    lines: dict = {(): 1}
    if not tokens:
        return None, lines
    data, idx = _node(tokens, 0, tokens[0].indent, (), lines)
    if idx != len(tokens):
        raise MiniYAMLError("unexpected content after document body",
                            tokens[idx].lineno)
    return data, lines


# ── tokenization ──────────────────────────────────────────────────────

def _tokenize(text: str) -> list:
    physical = text.split("\n")
    tokens: list = []
    i = 0
    while i < len(physical):
        i = _tokenize_line(physical, i, tokens)
    return tokens


def _tokenize_line(physical: list, i: int, tokens: list) -> int:
    raw = physical[i]
    lineno = i + 1
    if raw.strip() == "" or raw.lstrip().startswith("#"):
        return i + 1
    indent = _leading_indent(raw, lineno)
    stripped = raw[indent:]
    _reject_doc_marker(stripped, lineno)
    content = _strip_comment(stripped)
    if content == "":
        return i + 1
    if _is_block_header(content):
        body, end = _consume_block(physical, i, indent)
        tokens.append(Token(indent, content, lineno, _render_block(body)))
        return end
    tokens.append(Token(indent, content, lineno, None))
    return i + 1


def _leading_indent(raw: str, lineno: int) -> int:
    ws = re.match(r"[ \t]*", raw).group()
    if "\t" in ws:
        raise MiniYAMLError("tab in indentation is not permitted", lineno)
    return len(ws)


def _reject_doc_marker(stripped: str, lineno: int) -> None:
    if stripped == "---" or stripped.startswith("--- ") or stripped == "...":
        raise MiniYAMLError("multi-document streams are not supported", lineno)


def _quote_state(ch: str, in_s: bool, in_d: bool):
    if ch == "'" and not in_d:
        return not in_s, in_d
    if ch == '"' and not in_s:
        return in_s, not in_d
    return in_s, in_d


def _strip_comment(s: str) -> str:
    in_s = in_d = False
    for k, ch in enumerate(s):
        if ch in "'\"":
            in_s, in_d = _quote_state(ch, in_s, in_d)
        elif ch == "#" and not in_s and not in_d and (k == 0 or s[k - 1] == " "):
            return s[:k].rstrip()
    return s.rstrip()


# ── block scalars (``key: |``) ────────────────────────────────────────

def _is_block_header(content: str) -> bool:
    idx = _find_kv_colon(content)
    return idx != -1 and content[idx + 1:].strip() == "|"


def _consume_block(physical: list, i: int, key_indent: int):
    body: list = []
    for j in range(i + 1, len(physical)):
        line = physical[j]
        if line.strip() == "":
            body.append("")
            continue
        if _leading_indent(line, j + 1) <= key_indent:
            return body, j
        body.append(line)
    return body, len(physical)


def _render_block(body: list) -> str:
    nonblank = [ln for ln in body if ln.strip() != ""]
    if not nonblank:
        return ""
    base = min(_indent_width(ln) for ln in nonblank)
    out = [ln[base:] for ln in body]
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n" if out else ""


def _indent_width(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


# ── key/value splitting ───────────────────────────────────────────────

def _find_kv_colon(content: str) -> int:
    in_s = in_d = False
    end = len(content) - 1
    for k, ch in enumerate(content):
        if ch in "'\"":
            in_s, in_d = _quote_state(ch, in_s, in_d)
        elif ch == ":" and not in_s and not in_d and (k == end or content[k + 1] == " "):
            return k
    return -1


def _split_kv(token: Token):
    idx = _find_kv_colon(token.content)
    if idx == -1:
        raise MiniYAMLError(f"expected 'key: value', got {token.content!r}",
                            token.lineno)
    key = _scalar_key(token.content[:idx].strip(), token.lineno)
    valtext = token.content[idx + 1:].strip()
    if valtext == "|" and token.block is not None:
        return key, "", token.block
    return key, valtext, None


def _scalar_key(raw: str, lineno: int) -> str:
    if raw[:1] in "'\"":
        return str(_scalar(raw, lineno))
    return raw


# ── scalars ───────────────────────────────────────────────────────────

def _scalar(text: str, lineno: int):
    if text in _CONSTS:
        return _CONSTS[text]
    first = text[0]
    if first in "'\"":
        return _quoted(text, first, lineno)
    if first in "&*!":
        raise MiniYAMLError("anchors, aliases and tags are not supported", lineno)
    collection = _collection_literal(text, lineno)
    if collection is not _MISSING:
        return collection
    return _number(text, first, lineno)


def _collection_literal(text: str, lineno: int):
    if text == "[]":
        return []
    if text == "{}":
        return {}
    if text[0] in "[{":
        raise MiniYAMLError("flow collections are not supported", lineno)
    return _MISSING


def _number(text: str, first: str, lineno: int):
    if first in "0123456789+-.":
        if _INT.match(text):
            return int(text)
        if _FLOAT.match(text):
            return float(text)
    if _is_ambiguous(text):
        raise MiniYAMLError(
            f"ambiguous scalar {text!r}: quote it so its type is explicit",
            lineno)
    return text


def _is_ambiguous(text: str) -> bool:
    """True for YAML-1.1 tokens (octal/hex/binary/sexagesimal/underscored
    numbers, yes/no/on/off, .inf/.nan) that safe_load would type as a
    non-string but miniyaml's narrow grammar does not -- refuse, never guess."""
    if _YAML11.match(text):
        return True
    core = text[1:] if text[:1] in "+-" else text
    return "_" in core and bool(_UNDERSCORE_NUM.match(core))


def _quoted(text: str, first: str, lineno: int) -> str:
    if first == "'":
        return _single_quoted(text, lineno)
    return _double_quoted(text, lineno)


def _single_quoted(text: str, lineno: int) -> str:
    if len(text) < 2 or text[-1] != "'":
        raise MiniYAMLError("unterminated single-quoted string", lineno)
    return text[1:-1].replace("''", "'")


def _double_quoted(text: str, lineno: int) -> str:
    if len(text) < 2 or text[-1] != '"':
        raise MiniYAMLError("unterminated double-quoted string", lineno)
    body = text[1:-1]
    for src, dst in (("\\n", "\n"), ("\\t", "\t"), ("\\r", "\r"),
                     ('\\"', '"'), ("\\\\", "\\")):
        body = body.replace(src, dst)
    return body


# ── recursive descent ─────────────────────────────────────────────────

def _is_seq(token: Token) -> bool:
    return token.content == "-" or token.content.startswith("- ")


def _node(tokens: list, i: int, indent: int, path: tuple, lines: dict):
    token = tokens[i]
    if _is_seq(token):
        return _seq(tokens, i, indent, path, lines)
    if _find_kv_colon(token.content) != -1:
        return _map(tokens, i, indent, path, lines)
    return _scalar(token.content, token.lineno), i + 1


def _map(tokens: list, i: int, indent: int, path: tuple, lines: dict):
    result: dict = {}
    while i < len(tokens) and tokens[i].indent == indent and not _is_seq(tokens[i]):
        token = tokens[i]
        key, valtext, block = _split_kv(token)
        if key in result:
            raise MiniYAMLError(f"duplicate key {key!r}", token.lineno)
        kpath = path + (key,)
        lines[kpath] = token.lineno
        if block is not None:
            result[key], i = block, i + 1
        elif valtext == "":
            result[key], i = _child(tokens, i, indent, kpath, lines)
        else:
            result[key], i = _scalar(valtext, token.lineno), i + 1
    return result, i


def _child(tokens: list, i: int, parent_indent: int, path: tuple, lines: dict):
    nxt = i + 1
    if nxt >= len(tokens):
        return None, i + 1
    deeper = tokens[nxt].indent > parent_indent
    sibling_seq = tokens[nxt].indent == parent_indent and _is_seq(tokens[nxt])
    if deeper or sibling_seq:
        return _node(tokens, nxt, tokens[nxt].indent, path, lines)
    return None, i + 1


def _seq(tokens: list, i: int, indent: int, path: tuple, lines: dict):
    items: list = []
    while i < len(tokens) and tokens[i].indent == indent and _is_seq(tokens[i]):
        token = tokens[i]
        ipath = path + (len(items),)
        lines[ipath] = token.lineno
        rest = token.content[1:].strip()
        if rest == "" and token.block is None:
            child, i = _child(tokens, i, indent, ipath, lines)
        else:
            tokens[i] = token._replace(indent=indent + 2, content=rest)
            child, i = _node(tokens, i, indent + 2, ipath, lines)
        items.append(child)
    return items, i
