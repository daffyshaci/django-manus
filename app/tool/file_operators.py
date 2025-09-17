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
        """Map user-provided path to sandbox workspace POSIX path when needed.

        Rules:
        - Always canonicalize to '/workspace' inside the sandbox to avoid leaking host paths.
        - If path already starts with '/workspace', keep as is.
        - If path starts with '/' but NOT with '/workspace', interpret it as inside '/workspace'.
        - If path is an absolute HOST path under config.workspace_root, remap to '/workspace/<relative>'.
        - If path is an absolute HOST path outside workspace_root, place under '/workspace/<basename>'.
        - Otherwise, treat as relative and place under '/workspace/<path>'.
        """
        p_str = str(path)
        posix = p_str.replace("\\", "/")
        canonical = "/workspace"
        work_dir = (
            (config.sandbox.work_dir if config.sandbox else canonical).replace("\\", "/").rstrip("/")
        )

        # Already in canonical sandbox workspace
        if posix == canonical or posix.startswith(canonical + "/"):
            return posix

        # Paths under configured work_dir (host-style or posix) -> map to canonical
        if posix == work_dir or posix.startswith(work_dir + "/"):
            remainder = posix[len(work_dir):].lstrip("/")
            return canonical if not remainder else f"{canonical}/{remainder}"

        # Any other absolute posix path -> treat as inside canonical workspace
        if posix.startswith("/"):
            return f"{canonical}/{posix.lstrip('/')}"

        # Absolute host paths -> map under canonical workspace
        try:
            p = Path(p_str)
            if p.is_absolute():
                ws_root = Path(config.workspace_root) if getattr(config, "workspace_root", None) else None
                if ws_root and str(p).startswith(str(ws_root)):
                    rel = p.relative_to(ws_root)
                    return f"{canonical}/{rel.as_posix()}"
                return f"{canonical}/{p.name}"
        except Exception:
            # fall through to treat as relative
            pass

        # Relative path -> under canonical workspace
        return f"{canonical}/{posix}"

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
