import multiprocessing
import sys
import time
from io import StringIO
from typing import Dict

from app.tool.base import BaseTool


class PythonExecute(BaseTool):
    """A tool for executing Python code with timeout and safety restrictions.
        
        Default timeout is set to 30 seconds to handle more complex operations.
        You can override the timeout by passing a custom value.
        """

    name: str = "python_execute"
    description: str = "Executes Python code string with 30-second timeout (configurable). Note: Only print outputs are visible, function return values are not captured. Use print statements to see results."
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

    def _run_code(self, code: str, result_dict: dict, safe_globals: dict) -> None:
        original_stdout = sys.stdout
        try:
            output_buffer = StringIO()
            sys.stdout = output_buffer
            exec(code, safe_globals, safe_globals)
            result_dict["observation"] = output_buffer.getvalue()
            result_dict["success"] = True
        except Exception as e:
            result_dict["observation"] = str(e)
            result_dict["success"] = False
        finally:
            sys.stdout = original_stdout

    async def execute(
        self,
        code: str,
        timeout: int = 30,
    ) -> Dict:
        """
        Executes the provided Python code with a timeout.

        Args:
            code (str): The Python code to execute.
            timeout (int): Execution timeout in seconds.

        Returns:
            Dict: Contains 'output' with execution output or error message and 'success' status.
        """

        with multiprocessing.Manager() as manager:
            result = manager.dict({"observation": "", "success": False})
            if isinstance(__builtins__, dict):
                safe_globals = {"__builtins__": __builtins__}
            else:
                safe_globals = {"__builtins__": __builtins__.__dict__.copy()}
            proc = multiprocessing.Process(
                target=self._run_code, args=(code, result, safe_globals)
            )
            proc.start()
            proc.join(timeout)

            # timeout process
            if proc.is_alive():
                proc.terminate()
                proc.join(1)
                if proc.is_alive():
                    proc.kill()  # Force kill if terminate didn't work
                    proc.join()
                return {
                    "observation": f"Execution timeout after {timeout} seconds. Consider optimizing your code or increasing the timeout parameter.",
                    "success": False,
                }
            
            # Check if process exited normally
            if proc.exitcode != 0 and result.get("success", False):
                return {
                    "observation": f"Process exited with code {proc.exitcode}. This might indicate a critical error.",
                    "success": False,
                }
            
            return dict(result)
