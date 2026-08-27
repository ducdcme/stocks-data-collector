import os
import subprocess
import sys
from pathlib import Path


def _run_config(tmp_path: Path, extra_env: dict[str, str] | None = None) -> str:
    (tmp_path / ".env").write_text(
        "STOCKS_PROVIDER_PRIMARY=ssi\nSTOCKS_PROVIDER_FALLBACK=vnstock\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("STOCKS_PROVIDER_PRIMARY", None)
    env.pop("STOCKS_PROVIDER_FALLBACK", None)
    if extra_env:
        env.update(extra_env)
    project_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(project_root)
    result = subprocess.run(
        [sys.executable, "-c", "from app.config import settings; print(settings.primary_provider, settings.fallback_provider)"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_dotenv_loads_defaults(tmp_path):
    assert _run_config(tmp_path) == "ssi vnstock"


def test_os_environment_overrides_dotenv(tmp_path):
    assert _run_config(tmp_path, {"STOCKS_PROVIDER_PRIMARY": "vnstock", "STOCKS_PROVIDER_FALLBACK": "ssi"}) == "vnstock ssi"
