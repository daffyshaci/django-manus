import os
import pytest
import pytest_asyncio

from app.sandbox.client import create_sandbox_client, DaytonaSandboxClient
from app.config import config, SandboxSettings


def test_create_sandbox_client_daytona(monkeypatch):
    """Ensure create_sandbox_client selects Daytona when configured."""
    # Backup existing sandbox settings
    old_settings = config._config.sandbox
    try:
        # Force provider to daytona for this test
        config._config.sandbox = SandboxSettings(provider="daytona", use_sandbox=True)
        client = create_sandbox_client()
        assert isinstance(client, DaytonaSandboxClient)
    finally:
        config._config.sandbox = old_settings


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("DAYTONA_API_KEY"), reason="Daytona credentials not provided"
)
async def test_daytona_smoke_create_and_cleanup():
    """Smoke test to create a Daytona sandbox, run a trivial command, and cleanup.
    This test is skipped automatically unless DAYTONA_API_KEY is set.
    """
    client = DaytonaSandboxClient()
    await client.create()
    out = await client.run_command("echo hello-daytona")
    assert "hello-daytona" in (out or "")
    await client.cleanup()