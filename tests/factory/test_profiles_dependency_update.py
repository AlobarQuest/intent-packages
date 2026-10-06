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
    cmds = dep.TOOLING_PROFILES["pip"].mutation_commands(
        tmp_path, "fastapi", "0.139.0", "0.139.2", sites
    )
    assert cmds == ["sed -i 's/^fastapi==0.139.0$/fastapi==0.139.2/' requirements.txt"]


def test_pip_verifier_is_grep(tmp_path):
    sites = [dep.PinSite("requirements.txt", "requirements.txt", "0.139.0")]
    v = dep.TOOLING_PROFILES["pip"].verifier_commands(
        tmp_path, "fastapi", "0.139.0", "0.139.2", sites
    )
    assert v == ["grep -qx 'fastapi==0.139.2' requirements.txt"]


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
    cmds = dep.TOOLING_PROFILES["uv"].mutation_commands(
        tmp_path, "fastapi", "0.139.0", "0.139.2", sites
    )
    assert cmds == ["uv add 'fastapi>=0.139.2'"]


def test_uv_mutation_dev_only_adds_dev_flag(tmp_path):
    sites = [dep.PinSite("pyproject.toml", "dependency-groups.dev", "0.15.20")]
    cmds = dep.TOOLING_PROFILES["uv"].mutation_commands(
        tmp_path, "ruff", "0.15.20", "0.15.21", sites
    )
    assert cmds == ["uv add --dev 'ruff>=0.15.21'"]


def test_uv_verifier_is_lock_check(tmp_path):
    sites = [dep.PinSite("pyproject.toml", "project.dependencies", "0.139.0")]
    assert dep.TOOLING_PROFILES["uv"].verifier_commands(tmp_path, "fastapi", "0", "1", sites) == [
        "uv lock --check"
    ]


def test_uv_mutation_optional_only_uses_optional_flag(tmp_path):
    # A single optional-dependencies site must target that extra, not --dev.
    sites = [dep.PinSite("pyproject.toml", "optional-dependencies.dev", "0.15.21")]
    cmds = dep.TOOLING_PROFILES["uv"].mutation_commands(
        tmp_path, "ruff", "0.15.21", "0.15.22", sites
    )
    assert cmds == ["uv add --optional dev 'ruff>=0.15.22'"]


def test_uv_mutation_dual_site_defers_lock(tmp_path):
    # ruff pinned in both dependency-groups.dev and optional-dependencies.dev
    # (the security-standards shape): each add must be --frozen so no
    # intermediate lock sees the divergent pins, then one uv lock resolves.
    sites = [
        dep.PinSite("pyproject.toml", "dependency-groups.dev", "0.15.21"),
        dep.PinSite("pyproject.toml", "optional-dependencies.dev", "0.15.21"),
    ]
    cmds = dep.TOOLING_PROFILES["uv"].mutation_commands(
        tmp_path, "ruff", "0.15.21", "0.15.22", sites
    )
    assert cmds == [
        "uv add --frozen --dev 'ruff>=0.15.22'",
        "uv add --frozen --optional dev 'ruff>=0.15.22'",
        "uv lock",
    ]


def test_uv_mutation_named_group_uses_group_flag(tmp_path):
    sites = [
        dep.PinSite("pyproject.toml", "dependency-groups.lint", "1.0.0"),
        dep.PinSite("pyproject.toml", "project.dependencies", "1.0.0"),
    ]
    cmds = dep.TOOLING_PROFILES["uv"].mutation_commands(tmp_path, "tool", "1.0.0", "1.1.0", sites)
    assert cmds == [
        "uv add --frozen --group lint 'tool>=1.1.0'",
        "uv add --frozen 'tool>=1.1.0'",
        "uv lock",
    ]


def test_build_envelope_uv_dual_site_orders_mutators_before_verifier(tmp_path):
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
        repo=tmp_path,
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
    assert env["constraints"]["verify_commands"] == ["uv lock --check"]


def test_build_envelope_shape_matches_contract(tmp_path):
    sites = [dep.PinSite("requirements.txt", "requirements.txt", "0.139.0")]
    env = dep.build_envelope(
        "AlobarQuest/brain",
        "pip",
        "fastapi",
        "0.139.0",
        "0.139.2",
        {"accepted_standards": [], "standards_touched": ["project"], "status": "green"},
        sites,
        repo=tmp_path,
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
    assert env["constraints"]["verify_commands"] == [
        "grep -qx 'fastapi==0.139.2' requirements.txt",
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
    cmds = dep.TOOLING_PROFILES["npm"].mutation_commands(tmp_path, "zod", "3.23.8", "3.24.0", sites)
    assert cmds == ["npm install zod@3.24.0 --save-exact"]
    v = dep.TOOLING_PROFILES["npm"].verifier_commands(tmp_path, "zod", "3.23.8", "3.24.0", sites)
    assert v == ['grep -q \'"zod": "3.24.0"\' package.json']


def test_npm_mutation_grants_the_build_when_one_is_declared(tmp_path):
    """The envelope is the agent's ENTIRE command vocabulary, so it must be complete.

    factory-runner writes a PreToolUse hook from `constraints.allowed_commands` and
    Claude Code exact-matches every Bash call against it, so a command absent here is
    one the agent cannot run. Measured 2026-08-19: with the build omitted, the zod
    3 -> 4 agent attempted it, was refused, and moved the pin instead.
    """
    _write(
        tmp_path,
        "package.json",
        _json.dumps({"scripts": {"build": "tsc"}, "devDependencies": {"typescript": "5.9.3"}}),
    )
    sites = dep.TOOLING_PROFILES["npm"].discover_pin_sites(tmp_path, "typescript")
    cmds = dep.TOOLING_PROFILES["npm"].mutation_commands(
        tmp_path, "typescript", "5.9.3", "7.0.2", sites
    )
    assert cmds == ["npm install typescript@7.0.2 --save-exact --save-dev", "npm run build"]


def test_the_build_is_deferred_from_authoring(tmp_path):
    """Granted to the agent, withheld from the dry run. Both halves, or neither works."""
    _write(tmp_path, "package.json", _json.dumps({"scripts": {"build": "tsc"}}))
    assert dep.commands_deferred_to_coding(tmp_path, "npm") == ("npm run build",)


def test_a_test_script_is_deferred_even_without_a_build_script(tmp_path):
    """`npm test` defers on its own merits, not as a rider on the build.

    This asserted `== ()` until 2026-09-03, when `npm test` came off the runner-honesty
    deny-list: its fixture declares a test script, so the old assertion said "a repository
    whose gate runs tests defers nothing", which is the state that let unit ac6f1dd6 ship a
    change that compiled and threw.
    """
    _write(tmp_path, "package.json", _json.dumps({"scripts": {"test": "vitest run"}}))
    assert dep.commands_deferred_to_coding(tmp_path, "npm") == ("npm test",)


def test_nothing_is_deferred_when_the_repo_declares_no_gate(tmp_path):
    """The genuine empty case: no build, no test, no eslint config, no prettier config."""
    _write(tmp_path, "package.json", _json.dumps({"scripts": {"start": "node ."}}))
    assert dep.commands_deferred_to_coding(tmp_path, "npm") == ()


def test_the_gate_components_are_each_gated_on_their_own_marker(tmp_path):
    """A repository without the tool must not be handed a command it cannot run."""
    _write(tmp_path, "package.json", _json.dumps({"scripts": {"test": "vitest run"}}))
    _write(tmp_path, "eslint.config.mjs", "export default [];\n")

    deferred = dep.commands_deferred_to_coding(tmp_path, "npm")

    assert "npx eslint ." in deferred
    assert "npm test" in deferred
    assert not any("prettier" in command for command in deferred), (
        "prettier was named without a .prettierrc for it to run against"
    )


def test_nothing_is_deferred_for_other_tooling(tmp_path):
    _write(tmp_path, "package.json", _json.dumps({"scripts": {"build": "tsc"}}))
    assert dep.commands_deferred_to_coding(tmp_path, "uv") == ()


def test_every_deferred_command_is_in_the_envelope(tmp_path):
    """A deferred command absent from the envelope would silently narrow the dry run."""
    _write(
        tmp_path,
        "package.json",
        _json.dumps({"scripts": {"build": "tsc"}, "devDependencies": {"typescript": "5.9.3"}}),
    )
    sites = dep.TOOLING_PROFILES["npm"].discover_pin_sites(tmp_path, "typescript")
    env = dep.build_envelope(
        "AlobarQuest/infraops-mcp-server",
        "npm",
        "typescript",
        "5.9.3",
        "7.0.2",
        {"accepted_standards": [], "standards_touched": ["code"], "status": "green"},
        sites,
        repo=tmp_path,
    )
    allowed = env["constraints"]["allowed_commands"]
    assert set(dep.commands_deferred_to_coding(tmp_path, "npm")) <= set(allowed)


def test_coding_note_tells_the_agent_to_build_when_the_repo_declares_one(tmp_path):
    """What `allowed_commands` can no longer carry, the outcome does."""
    _write(tmp_path, "package.json", _json.dumps({"scripts": {"build": "tsc"}}))
    note = dep.coding_note(tmp_path, "npm")
    assert note is not None
    assert "build" in note


def test_coding_note_is_absent_without_a_build_script(tmp_path):
    _write(tmp_path, "package.json", _json.dumps({"scripts": {"test": "vitest run"}}))
    assert dep.coding_note(tmp_path, "npm") is None


def test_coding_note_is_absent_for_other_tooling(tmp_path):
    _write(tmp_path, "package.json", _json.dumps({"scripts": {"build": "tsc"}}))
    assert dep.coding_note(tmp_path, "uv") is None


def test_npm_mutation_omits_the_build_when_the_repo_declares_none(tmp_path):
    _write(
        tmp_path,
        "package.json",
        _json.dumps({"scripts": {"test": "vitest run"}, "dependencies": {"zod": "3.23.8"}}),
    )
    sites = dep.TOOLING_PROFILES["npm"].discover_pin_sites(tmp_path, "zod")
    cmds = dep.TOOLING_PROFILES["npm"].mutation_commands(tmp_path, "zod", "3.23.8", "3.24.0", sites)
    assert cmds == ["npm install zod@3.24.0 --save-exact"]


def test_npm_mutation_omits_the_build_when_the_repo_declares_no_scripts(tmp_path):
    _write(tmp_path, "package.json", _json.dumps({"dependencies": {"zod": "3.23.8"}}))
    sites = dep.TOOLING_PROFILES["npm"].discover_pin_sites(tmp_path, "zod")
    cmds = dep.TOOLING_PROFILES["npm"].mutation_commands(tmp_path, "zod", "3.23.8", "3.24.0", sites)
    assert cmds == ["npm install zod@3.24.0 --save-exact"]


def test_build_envelope_npm_grants_the_build_and_verifies_with_npm_ci(tmp_path):
    """The agent gets the build; npm ci verifies. `mutation_commands` stays an ordered subset."""
    _write(
        tmp_path,
        "package.json",
        _json.dumps({"scripts": {"build": "tsc"}, "devDependencies": {"typescript": "5.9.3"}}),
    )
    _write(tmp_path, "package-lock.json", _json.dumps({"lockfileVersion": 3}))
    sites = dep.TOOLING_PROFILES["npm"].discover_pin_sites(tmp_path, "typescript")
    env = dep.build_envelope(
        "AlobarQuest/infraops-mcp-server",
        "npm",
        "typescript",
        "5.9.3",
        "7.0.2",
        {"accepted_standards": [], "standards_touched": ["code"], "status": "green"},
        sites,
        repo=tmp_path,
    )
    install = "npm install typescript@7.0.2 --save-exact --save-dev"
    grep = 'grep -q \'"typescript": "7.0.2"\' package.json'
    assert env["constraints"]["allowed_commands"] == [install, "npm run build", "npm ci", grep]
    assert env["constraints"]["mutation_commands"] == [install, "npm run build"]
    # The build is a mutator, so it is not in the verify script, which is exactly the verifiers:
    # finalize runs the same commands in the same order it ran before `verify_commands` existed.
    assert env["constraints"]["verify_commands"] == ["npm ci", grep]


def test_npm_verifier_runs_npm_ci_when_the_repo_tracks_a_lockfile(tmp_path):
    """`npm install` and `npm ci` disagree, and the repository's gate runs the second.

    npm install resolves a workable tree; npm ci installs the resulting lockfile strictly
    and refuses it when a peer range is unsatisfied. On 2026-08-19 typescript 7.0.2 passed
    every validation here and failed the target repository's named check at dependency
    installation, because typescript-eslint declares `peer typescript >=4.8.4 <6.1.0`.
    `dry_run_mutation` runs this whole list, so naming npm ci moves that refusal to
    authoring time.
    """
    _write(tmp_path, "package.json", _json.dumps({"devDependencies": {"typescript": "5.9.3"}}))
    _write(tmp_path, "package-lock.json", _json.dumps({"lockfileVersion": 3}))
    sites = dep.TOOLING_PROFILES["npm"].discover_pin_sites(tmp_path, "typescript")
    assert dep.TOOLING_PROFILES["npm"].verifier_commands(
        tmp_path, "typescript", "5.9.3", "7.0.2", sites
    ) == ["npm ci", 'grep -q \'"typescript": "7.0.2"\' package.json']


def test_npm_verifier_omits_npm_ci_without_a_lockfile(tmp_path):
    """npm ci requires a lockfile and fails without one, so it is not declared then."""
    _write(tmp_path, "package.json", _json.dumps({"dependencies": {"zod": "3.23.8"}}))
    sites = dep.TOOLING_PROFILES["npm"].discover_pin_sites(tmp_path, "zod")
    assert dep.TOOLING_PROFILES["npm"].verifier_commands(
        tmp_path, "zod", "3.23.8", "3.24.0", sites
    ) == ['grep -q \'"zod": "3.24.0"\' package.json']


def _envelopes_for_every_tooling(tmp_path):
    """One real envelope per tooling profile, each built against its own minimal checkout."""
    green = {"accepted_standards": [], "standards_touched": ["project"], "status": "green"}
    pip_repo = tmp_path / "pip"
    pip_repo.mkdir()
    _write(pip_repo, "requirements.txt", "fastapi==0.139.0\n")
    uv_repo = tmp_path / "uv"
    uv_repo.mkdir()
    _write(uv_repo, "pyproject.toml", '[dependency-groups]\ndev = ["ruff==0.15.21"]\n')
    npm_repo = tmp_path / "npm"
    npm_repo.mkdir()
    _write(
        npm_repo,
        "package.json",
        _json.dumps({"scripts": {"build": "tsc"}, "devDependencies": {"typescript": "5.9.3"}}),
    )
    _write(npm_repo, "package-lock.json", _json.dumps({"lockfileVersion": 3}))
    cases = (
        ("pip", pip_repo, "fastapi", "0.139.0", "0.139.2"),
        ("uv", uv_repo, "ruff", "0.15.21", "0.15.22"),
        ("npm", npm_repo, "typescript", "5.9.3", "7.0.2"),
    )
    for tooling, repo, package, old, new in cases:
        sites = dep.TOOLING_PROFILES[tooling].discover_pin_sites(repo, package)
        assert sites, tooling
        yield (
            tooling,
            dep.build_envelope(
                "AlobarQuest/brain", tooling, package, old, new, green, sites, repo=repo
            ),
        )


def test_every_profile_s_verify_script_is_one_the_runner_accepts(tmp_path):
    """SDS 1.1 3c-1: factory-runner and the orchestrator refuse anything else at ingress."""
    for tooling, env in _envelopes_for_every_tooling(tmp_path):
        constraints = env["constraints"]
        verify = constraints["verify_commands"]
        assert verify, tooling
        assert all(command in constraints["allowed_commands"] for command in verify), tooling
        assert not set(verify) & set(constraints["mutation_commands"]), tooling


def test_declaring_the_verify_script_changes_nothing_finalize_runs(tmp_path):
    """The script with the key (mutators in allowed order, then verify_commands) equals the
    script without it (allowed_commands), so no profile envelope runs differently."""
    for tooling, env in _envelopes_for_every_tooling(tmp_path):
        constraints = env["constraints"]
        mutations = set(constraints["mutation_commands"])
        script = [command for command in constraints["allowed_commands"] if command in mutations]
        assert script + constraints["verify_commands"] == constraints["allowed_commands"], tooling


def test_a_profile_without_a_verifier_emits_no_verify_key(tmp_path, monkeypatch):
    """Absent and empty differ at the runner: a present key must be non-empty."""
    import dataclasses

    profile = dep.TOOLING_PROFILES["pip"]
    monkeypatch.setitem(
        dep.TOOLING_PROFILES,
        "pip",
        dataclasses.replace(profile, verifier_commands=lambda *_args: []),
    )
    _write(tmp_path, "requirements.txt", "fastapi==0.139.0\n")
    sites = dep.TOOLING_PROFILES["pip"].discover_pin_sites(tmp_path, "fastapi")

    env = dep.build_envelope(
        "AlobarQuest/brain",
        "pip",
        "fastapi",
        "0.139.0",
        "0.139.2",
        {"accepted_standards": [], "standards_touched": ["project"], "status": "green"},
        sites,
        repo=tmp_path,
    )

    assert "verify_commands" not in env["constraints"]
