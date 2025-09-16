"""File operation interfaces and sandbox-backed implementation.

This module exposes a single FileOperator implementation (SandboxFileOperator)
that proxies all file and shell operations to the Daytona sandbox client.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol, Tuple, Union, runtime_checkable

from app.config import SandboxSettings, config
from app.exceptions import ToolError
from app.sandbox.client import SANDBOX_CLIENT


PathLike = Union[str, Path]


@runtime_checkable
class FileOperator(Protocol):
    """Interface for file operations used by StrReplaceEditor and other tools."""

    async def read_file(self, path: PathLike) -> str: ...

    async def write_file(self, path: PathLike, content: str) -> None: ...

    async def is_directory(self, path: PathLike) -> bool: ...

    async def exists(self, path: PathLike) -> bool: ...

    async def run_command(
        self, cmd: str, timeout: Optional[float] = 120.0
    ) -> Tuple[int, str, str]: ...


class SandboxFileOperator(FileOperator):
    """File operations implementation for Daytona sandbox environment."""

    def __init__(self) -> None:
        self.sandbox_client = SANDBOX_CLIENT

    def _to_sandbox_path(self, path: PathLike) -> str:
        """Map host absolute path to sandbox workspace POSIX path when needed."""
        p_str = str(path)
        # Normalize to POSIX-like
        posix = p_str.replace("\\", "/")
        work_dir = (config.sandbox.work_dir if config.sandbox else "/workspace").rstrip("/")
        if posix.startswith(work_dir + "/") or posix == work_dir:
            return posix
        try:
            p = Path(p_str)
            if p.is_absolute():
                rel = p.relative_to(config.workspace_root)
                mapped = f"{work_dir}/{rel.as_posix()}"
                return mapped
        except Exception:
            # If cannot map, return normalized
            return posix
        return posix

    async def _ensure_sandbox_initialized(self) -> None:
        """Ensure sandbox is initialized before performing operations."""
        if not getattr(self.sandbox_client, "sandbox", None):
            await self.sandbox_client.create(
                config=config.sandbox or SandboxSettings(),
                conversation_id=getattr(self.sandbox_client, "_conversation_id", None),
            )

    async def read_file(self, path: PathLike) -> str:
        await self._ensure_sandbox_initialized()
        spath = self._to_sandbox_path(path)
        try:
            return await self.sandbox_client.read_file(str(spath))
        except Exception as e:  # pragma: no cover
            raise ToolError(f"Failed to read {path} in sandbox: {str(e)}") from None

    async def write_file(self, path: PathLike, content: str) -> None:
        await self._ensure_sandbox_initialized()
        spath = self._to_sandbox_path(path)
        try:
            await self.sandbox_client.write_file(str(spath), content)
        except Exception as e:  # pragma: no cover
            raise ToolError(f"Failed to write to {path} in sandbox: {str(e)}") from None

    async def is_directory(self, path: PathLike) -> bool:
        await self._ensure_sandbox_initialized()
        spath = self._to_sandbox_path(path)
        result = await self.sandbox_client.run_command(
            f"test -d {spath} && echo 'true' || echo 'false'"
        )
        return (result or "").strip() == "true"

    async def exists(self, path: PathLike) -> bool:
        await self._ensure_sandbox_initialized()
        spath = self._to_sandbox_path(path)
        result = await self.sandbox_client.run_command(
            f"test -e {spath} && echo 'true' || echo 'false'"
        )
        return (result or "").strip() == "true"

    async def run_command(
        self, cmd: str, timeout: Optional[float] = 120.0
    ) -> Tuple[int, str, str]:
        await self._ensure_sandbox_initialized()
        try:
            stdout = await self.sandbox_client.run_command(
                cmd, timeout=int(timeout) if timeout else None
            )
            # Current sandbox client returns stdout only; no explicit return code or stderr
            return 0, stdout, ""
        except TimeoutError as exc:  # pragma: no cover
            raise TimeoutError(
                f"Command '{cmd}' timed out after {timeout} seconds in sandbox"
            ) from exc
        except Exception as exc:  # pragma: no cover
            return 1, "", f"Error executing command in sandbox: {str(exc)}"
