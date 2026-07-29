import json as _json

from intent_packages.profiles import dependency_update as dep


def _write(tmp_path, name, text):
    (tmp_path / name).write_text(text, encoding="utf-8")


def test_pip_discovers_single_site(tmp_path):
    _write(tmp_path, "requirements.txt", "fastapi==0.139.0\nuvicorn==0.51.0\n")
    sites = dep.TOOLING_PROFILES["pip"].discover_pin_sites(tmp_path, "fastapi")
    assert [(s.file, s.current_version) for s in sites] == [("requirements.txt", "0.139.0")]


def test_pip_discovers_dual_site(tmp_path):
    _write(tmp_path, "requirements.txt", "httpx==0.28.1\n")
    _write(tmp_path, "requirements-dev.txt", "httpx==0.28.1\n")
    sites = dep.TOOLING_PROFILES["pip"].discover_pin_sites(tmp_path, "httpx")
    assert {s.file for s in sites} == {"requirements.txt", "requirements-dev.txt"}


def test_pip_mutation_commands_one_sed_per_site(tmp_path):
    sites = [dep.PinSite("requirements.txt", "requirements.txt", "0.139.0")]
    cmds = dep.TOOLING_PROFILES["pip"].mutation_commands("fastapi", "0.139.0", "0.139.2", sites)
    assert cmds == ["sed -i 's/^fastapi==0.139.0$/fastapi==0.139.2/' requirements.txt"]


def test_pip_verifier_is_grep(tmp_path):
    sites = [dep.PinSite("requirements.txt", "requirements.txt", "0.139.0")]
    v = dep.TOOLING_PROFILES["pip"].verifier_command("fastapi", "0.139.0", "0.139.2", sites)
    assert v == "grep -qx 'fastapi==0.139.2' requirements.txt"


def test_uv_discovers_project_and_group(tmp_path):
    _write(
        tmp_path,
        "pyproject.toml",
        (
            "[project]\n"
            'dependencies = ["fastapi==0.139.0"]\n'
            "[dependency-groups]\n"
            'dev = ["ruff==0.15.20", "fastapi==0.139.0"]\n'
        ),
    )
    sites = dep.TOOLING_PROFILES["uv"].discover_pin_sites(tmp_path, "fastapi")
    labels = sorted(s.label for s in sites)
    assert labels == ["dependency-groups.dev", "project.dependencies"]
    assert all(s.file == "pyproject.toml" and s.current_version == "0.139.0" for s in sites)


def test_uv_skips_unpinned_occurrence(tmp_path):
    _write(
        tmp_path,
        "pyproject.toml",
        ('[project]\ndependencies = ["fastapi==0.139.0", "httpx"]\n'),
    )
    # fastapi is pinned -> a site; httpx is unpinned -> not a site.
    assert [
        s.current_version
        for s in dep.TOOLING_PROFILES["uv"].discover_pin_sites(tmp_path, "fastapi")
    ] == ["0.139.0"]
    assert dep.TOOLING_PROFILES["uv"].discover_pin_sites(tmp_path, "httpx") == []


def test_uv_mutation_runtime_dep_no_dev_flag(tmp_path):
    sites = [dep.PinSite("pyproject.toml", "project.dependencies", "0.139.0")]
    cmds = dep.TOOLING_PROFILES["uv"].mutation_commands("fastapi", "0.139.0", "0.139.2", sites)
    assert cmds == ["uv add 'fastapi>=0.139.2'"]


def test_uv_mutation_dev_only_adds_dev_flag(tmp_path):
    sites = [dep.PinSite("pyproject.toml", "dependency-groups.dev", "0.15.20")]
    cmds = dep.TOOLING_PROFILES["uv"].mutation_commands("ruff", "0.15.20", "0.15.21", sites)
    assert cmds == ["uv add --dev 'ruff>=0.15.21'"]


def test_uv_verifier_is_lock_check(tmp_path):
    sites = [dep.PinSite("pyproject.toml", "project.dependencies", "0.139.0")]
    assert (
        dep.TOOLING_PROFILES["uv"].verifier_command("fastapi", "0", "1", sites) == "uv lock --check"
    )


def test_uv_mutation_optional_only_uses_optional_flag():
    # A single optional-dependencies site must target that extra, not --dev.
    sites = [dep.PinSite("pyproject.toml", "optional-dependencies.dev", "0.15.21")]
    cmds = dep.TOOLING_PROFILES["uv"].mutation_commands("ruff", "0.15.21", "0.15.22", sites)
    assert cmds == ["uv add --optional dev 'ruff>=0.15.22'"]


def test_uv_mutation_dual_site_defers_lock():
    # ruff pinned in both dependency-groups.dev and optional-dependencies.dev
    # (the security-standards shape): each add must be --frozen so no
    # intermediate lock sees the divergent pins, then one uv lock resolves.
    sites = [
        dep.PinSite("pyproject.toml", "dependency-groups.dev", "0.15.21"),
        dep.PinSite("pyproject.toml", "optional-dependencies.dev", "0.15.21"),
    ]
    cmds = dep.TOOLING_PROFILES["uv"].mutation_commands("ruff", "0.15.21", "0.15.22", sites)
    assert cmds == [
        "uv add --frozen --dev 'ruff>=0.15.22'",
        "uv add --frozen --optional dev 'ruff>=0.15.22'",
        "uv lock",
    ]


def test_uv_mutation_named_group_uses_group_flag():
    sites = [
        dep.PinSite("pyproject.toml", "dependency-groups.lint", "1.0.0"),
        dep.PinSite("pyproject.toml", "project.dependencies", "1.0.0"),
    ]
    cmds = dep.TOOLING_PROFILES["uv"].mutation_commands("tool", "1.0.0", "1.1.0", sites)
    assert cmds == [
        "uv add --frozen --group lint 'tool>=1.1.0'",
        "uv add --frozen 'tool>=1.1.0'",
        "uv lock",
    ]


def test_build_envelope_uv_dual_site_orders_mutators_before_verifier():
    sites = [
        dep.PinSite("pyproject.toml", "dependency-groups.dev", "0.15.21"),
        dep.PinSite("pyproject.toml", "optional-dependencies.dev", "0.15.21"),
    ]
    env = dep.build_envelope(
        "AlobarQuest/security-standards",
        "uv",
        "ruff",
        "0.15.21",
        "0.15.22",
        {"accepted_standards": [], "standards_touched": ["code"], "status": "green"},
        sites,
    )
    assert env["constraints"]["allowed_commands"] == [
        "uv add --frozen --dev 'ruff>=0.15.22'",
        "uv add --frozen --optional dev 'ruff>=0.15.22'",
        "uv lock",
        "uv lock --check",
    ]
    assert env["constraints"]["mutation_commands"] == [
        "uv add --frozen --dev 'ruff>=0.15.22'",
        "uv add --frozen --optional dev 'ruff>=0.15.22'",
        "uv lock",
    ]


def test_build_envelope_shape_matches_contract():
    sites = [dep.PinSite("requirements.txt", "requirements.txt", "0.139.0")]
    env = dep.build_envelope(
        "AlobarQuest/brain",
        "pip",
        "fastapi",
        "0.139.0",
        "0.139.2",
        {"accepted_standards": [], "standards_touched": ["project"], "status": "green"},
        sites,
    )
    assert "work_unit_id" not in env["constraints"]
    assert env["change_class"] == "dependency-update"
    assert env["constraints"]["allowed_commands"] == [
        "sed -i 's/^fastapi==0.139.0$/fastapi==0.139.2/' requirements.txt",
        "grep -qx 'fastapi==0.139.2' requirements.txt",
    ]
    assert env["constraints"]["mutation_commands"] == [
        "sed -i 's/^fastapi==0.139.0$/fastapi==0.139.2/' requirements.txt",
    ]
    assert env["capabilities"]["command.run"] == "allowed"


def test_npm_discovers_dependency(tmp_path):
    _write(
        tmp_path,
        "package.json",
        _json.dumps(
            {"dependencies": {"zod": "3.23.8"}, "devDependencies": {"typescript": "5.4.5"}}
        ),
    )
    sites = dep.TOOLING_PROFILES["npm"].discover_pin_sites(tmp_path, "zod")
    assert [(s.label, s.current_version) for s in sites] == [("dependencies", "3.23.8")]


def test_npm_mutation_and_verifier(tmp_path):
    sites = [dep.PinSite("package.json", "dependencies", "3.23.8")]
    cmds = dep.TOOLING_PROFILES["npm"].mutation_commands("zod", "3.23.8", "3.24.0", sites)
    assert cmds == ["npm install zod@3.24.0 --save-exact"]
    v = dep.TOOLING_PROFILES["npm"].verifier_command("zod", "3.23.8", "3.24.0", sites)
    assert v == 'grep -q \'"zod": "3.24.0"\' package.json'
