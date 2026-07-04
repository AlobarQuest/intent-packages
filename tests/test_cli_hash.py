from intent_packages.cli import main


def test_hash_subcommand_prints_64_hex(tmp_path, capsys):
    (tmp_path / "package.yaml").write_text(
        "package_id: p\nrevision: 1\nstatus: draft\n", encoding="utf-8"
    )
    rc = main(["hash", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert len(out) == 64 and all(c in "0123456789abcdef" for c in out)
