from __future__ import annotations

import io
import tokenize
from dataclasses import dataclass


def python_comment_tokens(content: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(content).readline):
            if tok.type == tokenize.COMMENT:
                out.append((int(tok.start[0]), str(tok.string)))
    except tokenize.TokenError:
        return out
    return out


def js_comment_tokens(lines: list[str]) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    in_block = False
    for i, line in enumerate(lines, 1):
        if in_block:
            out.append((i, line))
            in_block = "*/" not in line
            continue

        start, is_block = _comment_start(line)
        if start is None:
            continue
        out.append((i, line[start:]))
        if is_block:
            in_block = "*/" not in line[start:]
    return out


def _comment_start(line: str) -> tuple[int | None, bool]:
    idx_line = line.find("//")
    idx_block = line.find("/*")
    if idx_line < 0 and idx_block < 0:
        return None, False
    if idx_block >= 0 and (idx_line < 0 or idx_block < idx_line):
        return idx_block, True
    return idx_line, False


@dataclass(slots=True)
class _StripState:
    mode: str  # code | line_comment | block_comment | single | double | template
    escape: bool = False


def strip_js_ts_strings_and_comments(text: str) -> str:
    out: list[str] = []
    state = _StripState(mode="code", escape=False)
    i = 0
    while i < len(text):
        i += _strip_step(text, i, out, state)
    return "".join(out)


def _strip_step(text: str, i: int, out: list[str], state: _StripState) -> int:
    ch = text[i]
    nxt = text[i + 1] if i + 1 < len(text) else ""
    if state.mode == "line_comment":
        return _step_line_comment(ch, out, state)
    if state.mode == "block_comment":
        return _step_block_comment(ch, nxt, out, state)
    if state.mode == "single":
        return _step_string(ch, out, state, end="'")
    if state.mode == "double":
        return _step_string(ch, out, state, end='"')
    if state.mode == "template":
        return _step_string(ch, out, state, end="`")
    return _step_code(ch, nxt, out, state)


def _step_line_comment(ch: str, out: list[str], state: _StripState) -> int:
    if ch == "\n":
        state.mode = "code"
        out.append("\n")
    else:
        out.append(" ")
    return 1


def _step_block_comment(ch: str, nxt: str, out: list[str], state: _StripState) -> int:
    if ch == "*" and nxt == "/":
        state.mode = "code"
        out.append("  ")
        return 2
    out.append("\n" if ch == "\n" else " ")
    return 1


def _step_string(ch: str, out: list[str], state: _StripState, *, end: str) -> int:
    if state.escape:
        state.escape = False
        out.append(" " if ch != "\n" else "\n")
        return 1
    if ch == "\\":
        state.escape = True
        out.append(" ")
        return 1
    if ch == end:
        state.mode = "code"
    out.append("\n" if ch == "\n" else " ")
    return 1


def _step_code(ch: str, nxt: str, out: list[str], state: _StripState) -> int:
    if ch == "/" and nxt == "/":
        state.mode = "line_comment"
        out.append("  ")
        return 2
    if ch == "/" and nxt == "*":
        state.mode = "block_comment"
        out.append("  ")
        return 2
    if ch == "'":
        state.mode = "single"
        out.append(" ")
        return 1
    if ch == '"':
        state.mode = "double"
        out.append(" ")
        return 1
    if ch == "`":
        state.mode = "template"
        out.append(" ")
        return 1
    out.append(ch)
    return 1
