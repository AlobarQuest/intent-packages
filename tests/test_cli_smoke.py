import pytest

from intent_packages.cli import main


def test_no_subcommand_errors():
    with pytest.raises(SystemExit):
        main([])
