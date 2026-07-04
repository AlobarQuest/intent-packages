from __future__ import annotations

from pathlib import Path

import yaml


class LoadError(Exception):
    pass


class _NoDatesLoader(yaml.SafeLoader):
    """SafeLoader that never auto-parses timestamps into datetime/date objects,
    and rejects a mapping with a repeated key (SafeLoader's default silently
    keeps the last value, which would let a hand-authored package.yaml carry
    an ambiguous/conflicting duplicate key undetected)."""

    def construct_mapping(self, node, deep=False):
        seen: set = set()
        for key_node, _value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None,
                    None,
                    f"duplicate key {key!r} in mapping",
                    node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


# Drop YAML's implicit timestamp resolver so 2026-07-03T00:00:00Z loads as str.
_NoDatesLoader.yaml_implicit_resolvers = {
    ch: [(tag, regexp) for (tag, regexp) in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load_yaml_strict(text: str) -> dict:
    try:
        docs = list(yaml.load_all(text, Loader=_NoDatesLoader))
    except yaml.YAMLError as exc:  # noqa: BLE001
        raise LoadError(f"invalid YAML: {exc}") from exc
    if len(docs) != 1:
        raise LoadError(f"expected exactly one YAML document, found {len(docs)}")
    data = docs[0]
    if not isinstance(data, dict):
        raise LoadError("top-level YAML must be a mapping")
    return data


def load_package(pkg_dir: str | Path) -> dict:
    path = Path(pkg_dir) / "package.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LoadError(f"could not read {path.name}: {exc}") from exc
    return load_yaml_strict(text)


def load_lineage(pkg_dir: str | Path) -> dict:
    path = Path(pkg_dir) / "lineage.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LoadError(f"could not read {path.name}: {exc}") from exc
    return load_yaml_strict(text)
