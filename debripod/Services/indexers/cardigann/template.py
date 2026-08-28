from __future__ import annotations

import re
import shlex
from datetime import datetime
from typing import Any


class TemplateError(ValueError):
    pass


def _lookup(context: dict[str, Any], path: str, dot: Any = None) -> Any:
    if path == ".":
        return dot
    clean = path.lstrip(".")
    parts = clean.split(".") if clean else []
    current: Any = context
    for part in parts:
        if part in {"CurrentYear", "Year"} and (current is None or current == ""):
            current = datetime.now().year
            continue
        if isinstance(current, dict):
            key = next((key for key in current if str(key).casefold() == part.casefold()), None)
            current = current.get(key) if key is not None else None
        else:
            current = getattr(current, part, None)
        if current is None:
            return ""
    return current


def _split_args(expression: str) -> list[str]:
    lexer = shlex.shlex(expression, posix=True, punctuation_chars="()")
    lexer.whitespace_split = True
    lexer.commenters = ""
    output: list[str] = []
    for token in lexer:
        if token and set(token) <= {"(", ")"}:
            output.extend(token)
        else:
            output.append(token)
    return output


def _atom(token: str, context: dict[str, Any], dot: Any) -> Any:
    if token.startswith("."):
        return _lookup(context, token, dot)
    if token.casefold() in {"true", "false"}:
        return token.casefold() == "true"
    if token.casefold() in {"nil", "null"}:
        return None
    try:
        return int(token)
    except ValueError:
        return token


_FUNCTIONS = {"and", "or", "eq", "ne", "join", "re_replace"}


def _call(function: str, args: list[Any]) -> Any:
    if function == "and":
        value: Any = True
        for item in args:
            value = item
            if not item:
                break
        return value
    if function == "or":
        return next((item for item in args if item), args[-1] if args else False)
    if function == "eq":
        return len(args) >= 2 and args[0] == args[1]
    if function == "ne":
        return len(args) >= 2 and args[0] != args[1]
    if function == "join":
        return str(args[1] if len(args) > 1 else "").join(str(item) for item in (args[0] or []))
    if function == "re_replace":
        return re.sub(str(args[1]), str(args[2]), str(args[0])) if len(args) >= 3 else ""
    raise TemplateError(f"unsupported template function: {function}")


def _parse_value(tokens: list[str], index: int, context: dict[str, Any], dot: Any) -> tuple[Any, int]:
    if index >= len(tokens):
        return "", index
    token = tokens[index]
    if token == "(":
        if index + 1 >= len(tokens):
            raise TemplateError("unterminated template expression")
        function = tokens[index + 1]
        if function not in _FUNCTIONS:
            value, next_index = _parse_value(tokens, index + 1, context, dot)
            if next_index >= len(tokens) or tokens[next_index] != ")":
                raise TemplateError("unterminated grouped template value")
            return value, next_index + 1
        args: list[Any] = []
        index += 2
        while index < len(tokens) and tokens[index] != ")":
            value, index = _parse_value(tokens, index, context, dot)
            args.append(value)
        if index >= len(tokens):
            raise TemplateError("unterminated template expression")
        return _call(function, args), index + 1
    if token == ")":
        raise TemplateError("unexpected closing parenthesis")
    return _atom(token, context, dot), index + 1


def _evaluate_stage(expression: str, context: dict[str, Any], dot: Any) -> Any:
    tokens = _split_args(expression)
    if not tokens:
        return ""
    if tokens[0] in _FUNCTIONS:
        function = tokens[0]
        args: list[Any] = []
        index = 1
        while index < len(tokens):
            if tokens[index] == ")":
                index += 1
                continue
            value, index = _parse_value(tokens, index, context, dot)
            args.append(value)
        return _call(function, args)
    value, index = _parse_value(tokens, 0, context, dot)
    if index != len(tokens):
        raise TemplateError(f"unexpected template token: {tokens[index]}")
    return value


def _split_pipeline(expression: str) -> list[str]:
    output: list[str] = []
    start = 0
    quoted = ""
    escaped = False
    depth = 0
    for index, char in enumerate(expression):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quoted:
            escaped = True
            continue
        if quoted:
            if char == quoted:
                quoted = ""
            continue
        if char in {'"', "'"}:
            quoted = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "|" and depth == 0:
            output.append(expression[start:index].strip())
            start = index + 1
    output.append(expression[start:].strip())
    return output


def evaluate(expression: str, context: dict[str, Any], dot: Any = None) -> Any:
    pipelines = _split_pipeline(expression)
    value = _evaluate_stage(pipelines[0], context, dot)
    for pipeline in pipelines[1:]:
        pipe_tokens = _split_args(pipeline)
        if not pipe_tokens:
            continue
        pipe_args: list[Any] = []
        index = 1
        while index < len(pipe_tokens):
            item, index = _parse_value(pipe_tokens, index, context, dot)
            pipe_args.append(item)
        if pipe_tokens[0] == "re_replace" and len(pipe_args) >= 2:
            value = _call("re_replace", [value, *pipe_args])
        elif pipe_tokens[0] == "join" and pipe_args:
            value = _call("join", [value, *pipe_args])
        else:
            raise TemplateError(f"unsupported template function: {pipe_tokens[0]}")
    return value


_TOKEN = re.compile(r"{{-?\s*(.*?)\s*-?}}", re.S)


def render_template(template: Any, variables: dict[str, Any] | None = None, *, dot: Any = None) -> str:
    text = str(template or "")
    context = dict(variables or {})
    context.setdefault("CurrentYear", datetime.now().year)
    pieces = _TOKEN.split(text)

    def render_range(start: int, stop: set[str], local_dot: Any) -> tuple[str, int, str]:
        output: list[str] = []
        index = start
        while index < len(pieces):
            if index % 2 == 0:
                output.append(pieces[index])
                index += 1
                continue
            expression = pieces[index].strip()
            command = expression.split(None, 1)[0] if expression else ""
            if command in stop:
                return "".join(output), index + 1, command
            if command == "if":
                try:
                    condition = bool(evaluate(expression[3:].strip(), context, local_dot))
                except TemplateError as exc:
                    raise TemplateError(f"{exc} in {expression}") from exc
                yes, next_index, terminator = render_range(index + 1, {"else", "end"}, local_dot)
                no = ""
                if terminator == "else":
                    no, next_index, _ = render_range(next_index, {"end"}, local_dot)
                output.append(yes if condition else no)
                index = next_index
                continue
            if command == "range":
                values = evaluate(expression[6:].strip(), context, local_dot) or []
                body_start = index + 1
                _discarded, next_index, _ = render_range(body_start, {"end"}, local_dot)
                for item in values:
                    body, _same_end, _ = render_range(body_start, {"end"}, item)
                    output.append(body)
                index = next_index
                continue
            if command in {"else", "end"}:
                raise TemplateError(f"unexpected template token: {command}")
            try:
                value = evaluate(expression, context, local_dot)
            except TemplateError as exc:
                raise TemplateError(f"{exc} in {expression}") from exc
            output.append("" if value is None else str(value))
            index += 1
        return "".join(output), index, ""

    rendered, _index, _stop = render_range(0, set(), dot)
    return rendered


render = render_template
