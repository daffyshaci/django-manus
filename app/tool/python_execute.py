import time
from typing import Dict

from app.tool.base import BaseTool, ToolResult
from app.config import config
from app.sandbox.client import SANDBOX_CLIENT


class PythonExecute(BaseTool):
    """A tool for executing Python code safely inside the sandbox with timeout restrictions.
    Default timeout is set to 30 seconds; you can override it by passing a custom value.
    """

    name: str = "python_execute"
    description: str = "Executes Python code string inside sandbox with 30-second timeout (configurable). Note: Only print outputs are visible, function return values are not captured. Use print statements to see results."
    parameters: dict = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The Python code to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Execution timeout in seconds (default: 30).",
                "default": 30,
                "minimum": 1,
                "maximum": 300,
            },
        },
        "required": ["code"],
    }

    async def execute(
        self,
        code: str,
        timeout: int = 30,
    ) -> ToolResult:
        """Executes the provided Python code in the sandbox.
        Writes a temporary file into the sandbox workspace and executes it with python3/python.
        """
        try:
            if not getattr(SANDBOX_CLIENT, "sandbox", None):
                await SANDBOX_CLIENT.create(config=config.sandbox)
            work_dir = (config.sandbox.work_dir or "/workspace").rstrip("/")
            tmp_dir = f"{work_dir}/.manus_tmp"
            await SANDBOX_CLIENT.run_command(f"mkdir -p {tmp_dir}")
            filename = f"{tmp_dir}/exec_{int(time.time()*1000)}.py"
            await SANDBOX_CLIENT.write_file(filename, code)
            # Try python3 first, fallback to python; redirect stderr to stdout
            cmd = f"python3 {filename} 2>&1 || python {filename} 2>&1"
            output = await SANDBOX_CLIENT.run_command(cmd, timeout=timeout)
            return ToolResult(output=output, status="success")
        except Exception as e:
            return ToolResult(error=f"Sandbox python execution failed: {str(e)}", status="error")
