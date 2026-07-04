from __future__ import annotations

import hashlib


class CanonicalError(Exception):
    pass


def intent_core(package: dict) -> dict:
    core = dict(package)
    core.pop("status", None)
    return core


def _canon(obj) -> str:
    if obj is None or obj is True or obj is False:
        return {None: "null", True: "true", False: "false"}[obj]
    if isinstance(obj, float):
        raise CanonicalError("floats are not allowed in intent packages (quote the value)")
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, str):
        return _canon_str(obj)
    if isinstance(obj, list):
        return "[" + ",".join(_canon(v) for v in obj) + "]"
    if isinstance(obj, dict):
        items = sorted(obj.items(), key=lambda kv: kv[0])
        return "{" + ",".join(f"{_canon_str(str(k))}:{_canon(v)}" for k, v in items) + "}"
    raise CanonicalError(f"unhashable type in package: {type(obj).__name__}")


def _canon_str(s: str) -> str:
    # RFC 8785 string escaping: JSON minimal escapes, UTF-8 preserved.
    out = ['"']
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\f":
            out.append("\\f")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def jcs(obj) -> str:
    return _canon(obj)


def package_hash(package: dict) -> str:
    return hashlib.sha256(jcs(intent_core(package)).encode("utf-8")).hexdigest()
