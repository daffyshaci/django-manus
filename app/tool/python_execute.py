import time
import re
from typing import Dict

from app.tool.base import BaseTool, ToolResult
from app.config import config
from app.sandbox.client import SANDBOX_CLIENT


class PythonExecute(BaseTool):
    """A tool for executing code safely inside the sandbox with timeout restrictions.
    Default timeout is set to 30 seconds; you can override it by passing a custom value.

    Notes:
    - Use when you want to run python code or typescript code.
    - Always use sandbox POSIX paths; never use host OS paths like 'C:\\...'.
    - The sandbox working directory is: {directory}
    - You may refer to files with '/workspace/...' or use shorthand '/file.py' which maps to '/workspace/file.py'.
    - Use print() for outputs; return values are not captured.
    """.format(directory=config.sandbox.work_dir)

    # Exposed tool name for LLMs
    name: str = "code_execution"
    description: str = (
        "Execute Python or TypeScript code inside sandbox with a configurable timeout. "
        "Use when you want to run python code or typescript code.\n"
        "Note: Only print/console outputs are visible; function return values are not captured.\n"
        "Do NOT use host OS paths like 'C:\\...'. Always use sandbox POSIX paths. "
        "Use '/workspace/...' or shorthand '/file.py' to refer to '/workspace/file.py'. "
        f"Sandbox working directory: {config.sandbox.work_dir}"
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "The code to execute. Do NOT use host OS paths like 'C:\\...'. "
                    "Always use sandbox POSIX paths (e.g., '/workspace/...' or shorthand '/file.py' for '/workspace/file.py'). "
                    f"Sandbox working directory: {config.sandbox.work_dir}"
                ),
            },
            "language": {
                "type": "string",
                "description": "Language of the code snippet. Supported: 'python' (default), 'typescript'",
                "enum": ["python", "typescript"],
                "default": "python",
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

    # Simple heuristic for detecting when the input is actually a shell command
    _SHELL_PREFIX = re.compile(r"^\s*(python3?|node|ts-node|npm|npx|uv|pip|ls|cd|mkdir|rm|cat|echo|git|wget|curl|tar|unzip|zip|sed|awk|grep|find|chmod|chown)\b")

    async def execute(
        self,
        code: str,
        timeout: int = 30,
        language: str = "python",
        **kwargs,
    ) -> ToolResult:
        """Executes the provided code in the sandbox.
        Behavior:
        - If the input looks like a shell command, run it via run_command (guardrail alignment).
        - Otherwise, for Python: try primary code_run; on failure, robustly fallback to run_command.
        - For TypeScript: write to a temp .ts and execute with ts-node if available; fallback to an alternate ts-node loader.
        """
        try:
            # Reject host-OS path usage inside provided code snippet to prevent confusing ENOENT
            if re.search(r"[A-Za-z]:\\\\", code) or re.search(r"\\\\\\\\", code):
                return ToolResult(
                    error=(
                        "Invalid path usage detected in code. Do NOT use host OS paths like 'C:\\...'. "
                        "Always use sandbox POSIX paths like '/workspace/...' or shorthand '/file.py' for '/workspace/file.py'."
                    ),
                    status="error",
                )

            # Ensure sandbox exists
            if not getattr(SANDBOX_CLIENT, "sandbox", None):
                await SANDBOX_CLIENT.create(config=config.sandbox)

            # Guardrail: if looks like a shell command, route to run_command rather than rejecting
            if self._SHELL_PREFIX.search(code.strip()):
                out = await SANDBOX_CLIENT.run_command(code, timeout=timeout)
                return ToolResult(output=out, status="success")

            lang = (language or "python").lower()

            if lang == "python":
                # Primary: run via SDK code runner
                try:
                    output = await SANDBOX_CLIENT.code_run(code, timeout=timeout)
                    return ToolResult(output=output, status="success")
                except Exception:
                    # Fallback 1: write to temp file and execute with python3
                    tmp_path = "/workspace/.tmp_code_exec.py"
                    try:
                        await SANDBOX_CLIENT.write_file(tmp_path, code)
                        try:
                            output = await SANDBOX_CLIENT.run_command(f"python3 {tmp_path}", timeout=timeout)
                            return ToolResult(output=output, status="success")
                        except Exception:
                            # Fallback 2: try 'python'
                            output = await SANDBOX_CLIENT.run_command(f"python {tmp_path}", timeout=timeout)
                            return ToolResult(output=output, status="success")
                    except Exception as e:
                        return ToolResult(error=f"Sandbox python execution failed (fallback): {str(e)}", status="error")

            elif lang == "typescript":
                # Implement TS via ts-node if present. We avoid rejecting even if env not ready; provide actionable errors.
                tmp_path_ts = "/workspace/.tmp_code_exec.ts"
                try:
                    await SANDBOX_CLIENT.write_file(tmp_path_ts, code)
                except Exception as e:
                    return ToolResult(error=f"Failed to stage TypeScript code: {str(e)}", status="error")

                # Try ts-node direct
                try:
                    output = await SANDBOX_CLIENT.run_command(f"ts-node {tmp_path_ts}", timeout=timeout)
                    return ToolResult(output=output, status="success")
                except Exception:
                    # Fallback: try node with ts-node loader (ESM)
                    try:
                        output = await SANDBOX_CLIENT.run_command(
                            f"node --loader ts-node/esm {tmp_path_ts}", timeout=timeout
                        )
                        return ToolResult(output=output, status="success")
                    except Exception as e:
                        return ToolResult(
                            error=(
                                "TypeScript execution failed. Ensure ts-node is available in sandbox or use the 'bash' tool to run TypeScript via your preferred setup. "
                                f"Details: {str(e)}"
                            ),
                            status="error",
                        )

            else:
                return ToolResult(error=f"Unsupported language: {language}", status="error")

        except Exception as e:
            return ToolResult(error=f"Sandbox code execution failed: {str(e)}", status="error")
