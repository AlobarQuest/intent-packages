from intent_packages.profiles import dependency_update as dep


def _write(tmp_path, name, text):
    (tmp_path / name).write_text(text, encoding="utf-8")


def test_pip_discovers_single_site(tmp_path):
    _write(tmp_path, "requirements.txt", "fastapi==0.139.0\nuvicorn==0.51.0\n")
    sites = dep.PROFILES["pip"].discover_pin_sites(tmp_path, "fastapi")
    assert [(s.file, s.current_version) for s in sites] == [("requirements.txt", "0.139.0")]


def test_pip_discovers_dual_site(tmp_path):
    _write(tmp_path, "requirements.txt", "httpx==0.28.1\n")
    _write(tmp_path, "requirements-dev.txt", "httpx==0.28.1\n")
    sites = dep.PROFILES["pip"].discover_pin_sites(tmp_path, "httpx")
    assert {s.file for s in sites} == {"requirements.txt", "requirements-dev.txt"}


def test_pip_mutation_commands_one_sed_per_site(tmp_path):
    sites = [dep.PinSite("requirements.txt", "requirements.txt", "0.139.0")]
    cmds = dep.PROFILES["pip"].mutation_commands("fastapi", "0.139.0", "0.139.2", sites)
    assert cmds == ["sed -i 's/^fastapi==0.139.0$/fastapi==0.139.2/' requirements.txt"]


def test_pip_verifier_is_grep(tmp_path):
    sites = [dep.PinSite("requirements.txt", "requirements.txt", "0.139.0")]
    v = dep.PROFILES["pip"].verifier_command("fastapi", "0.139.0", "0.139.2", sites)
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
    sites = dep.PROFILES["uv"].discover_pin_sites(tmp_path, "fastapi")
    labels = sorted(s.label for s in sites)
    assert labels == ["dependency-groups.dev", "project.dependencies"]
    assert all(s.file == "pyproject.toml" and s.current_version == "0.139.0" for s in sites)


def test_uv_mutation_runtime_dep_no_dev_flag(tmp_path):
    sites = [dep.PinSite("pyproject.toml", "project.dependencies", "0.139.0")]
    cmds = dep.PROFILES["uv"].mutation_commands("fastapi", "0.139.0", "0.139.2", sites)
    assert cmds == ["uv add 'fastapi>=0.139.2'"]


def test_uv_mutation_dev_only_adds_dev_flag(tmp_path):
    sites = [dep.PinSite("pyproject.toml", "dependency-groups.dev", "0.15.20")]
    cmds = dep.PROFILES["uv"].mutation_commands("ruff", "0.15.20", "0.15.21", sites)
    assert cmds == ["uv add --dev 'ruff>=0.15.21'"]


def test_uv_verifier_is_lock_check(tmp_path):
    sites = [dep.PinSite("pyproject.toml", "project.dependencies", "0.139.0")]
    assert dep.PROFILES["uv"].verifier_command("fastapi", "0", "1", sites) == "uv lock --check"


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
