import shutil


def test_cli_available() -> None:
    """Check if the cli command is available"""
    assert shutil.which("dagster-uc") is not None
