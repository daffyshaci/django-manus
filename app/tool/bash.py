import asyncio
from typing import Optional

from app.exceptions import ToolError
from app.tool.base import BaseTool, CLIResult
from app.config import config
from app.sandbox.client import SANDBOX_CLIENT


_BASH_DESCRIPTION = """Execute a bash command in the sandboxed terminal.
* Long running commands: For commands that may run indefinitely, run them in the background and redirect output to a file, e.g. `python3 app.py > server.log 2>&1 &`.
* Interactive: If a command returns exit code `-1`, send a second call with empty `command` to retrieve additional logs, or send input text to STDIN by setting `command` to the text.
* Timeout: If a command execution result says "Command timed out.", retry running the command in the background.
"""


class Bash(BaseTool):
    """A tool for executing bash commands in a sandbox"""

    name: str = "bash"
    description: str = _BASH_DESCRIPTION
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute. Can be empty to view additional logs when previous exit code is `-1`. Can be `ctrl+c` to interrupt the currently running process.",
            },
            "restart": {
                "type": "boolean",
                "description": "Reinitialize sandbox (fresh session).",
                "default": False,
            },
            "timeout": {
                "type": "integer",
                "description": "Command timeout in seconds.",
                "default": 60,
                "minimum": 1,
                "maximum": 3600,
            },
        },
        "required": ["command"],
    }

    async def execute(
        self, command: str | None = None, restart: bool = False, timeout: int = 60, **kwargs
    ) -> CLIResult:
        # Always use sandbox
        if restart:
            try:
                await SANDBOX_CLIENT.cleanup()
            except Exception:
                pass
            # Recreate sandbox, preserving any conversation context already injected
            await SANDBOX_CLIENT.create(config=config.sandbox)
            return CLIResult(system="sandbox bash session restarted")

        # Ensure sandbox exists
        if not getattr(SANDBOX_CLIENT, "sandbox", None):
            await SANDBOX_CLIENT.create(config=config.sandbox)

        if command is None:
            raise ToolError("no command provided.")

        try:
            out = await SANDBOX_CLIENT.run_command(
                command, timeout=timeout or config.sandbox.timeout
            )
            return CLIResult(output=out)
        except asyncio.TimeoutError:
            raise ToolError(
                f"timed out: bash has not returned in {timeout} seconds and must be restarted",
            ) from None
        except Exception as e:
            return CLIResult(error=f"sandbox bash error: {str(e)}")


if __name__ == "__main__":
    bash = Bash()
    rst = asyncio.run(bash.execute("ls -l"))
    print(rst)
