import subprocess
import sys

from atra.config import ROOT


def test_dart_api_client_matches_the_openapi_document():
    result = subprocess.run([sys.executable, "tool/gen_api.py", "--check"],
                            cwd=ROOT / "apps" / "mobile", capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
