import subprocess
import sys
from pathlib import Path


def test_importing_server_does_not_import_foundry_export():
    """The live server must never pull in the Foundry exporter (offline runtime
    must not gain a network dependency). Import app.server in a clean subprocess
    and assert foundry_export is absent from sys.modules."""
    backend = Path(__file__).resolve().parents[1]
    code = (
        "import sys; import app.server; "
        "assert 'app.capture.foundry_export' not in sys.modules, "
        "'server must not import foundry_export'; print('OK')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=str(backend),
        capture_output=True, text=True,
        env={"PYTHONPATH": ".", "PATH": __import__("os").environ.get("PATH", ""),
             "TELLO_DISABLE": "1", "INTEL_MODEL": "off"},
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "OK" in result.stdout
