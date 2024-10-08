import shutil
def test_cli_available():
    assert shutil.which("dagster-uc") is not None