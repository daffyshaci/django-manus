from abc import ABC, abstractmethod
from typing import Dict, Optional, Protocol, Any

from app.config import SandboxSettings, config
from pathlib import Path
import os
import uuid
import base64
import shlex


class SandboxFileOperations(Protocol):
    """Protocol for sandbox file operations."""

    async def copy_from(self, container_path: str, local_path: str) -> None:
        """Copies file from container to local.

        Args:
            container_path: File path in container.
            local_path: Local destination path.
        """
        ...

    async def copy_to(self, local_path: str, container_path: str) -> None:
        """Copies file from local to container.

        Args:
            local_path: Local source file path.
            container_path: Destination path in container.
        """
        ...

    async def read_file(self, path: str) -> str:
        """Reads file content from container.

        Args:
            path: File path in container.

        Returns:
            str: File content.
        """
        ...

    async def write_file(self, path: str, content: str) -> None:
        """Writes content to file in container.

        Args:
            path: File path in container.
            content: Content to write.
        """
        ...


class BaseSandboxClient(ABC):
    """Base sandbox client interface."""

    @abstractmethod
    async def create(
        self,
        config: Optional[SandboxSettings] = None,
        volume_bindings: Optional[Dict[str, str]] = None,
        conversation_id: Optional[str] = None,
    ) -> None:
        """Creates sandbox."""

    @abstractmethod
    async def run_command(self, command: str, timeout: Optional[int] = None) -> str:
        """Executes command."""

    @abstractmethod
    async def copy_from(self, container_path: str, local_path: str) -> None:
        """Copies file from container."""

    @abstractmethod
    async def copy_to(self, local_path: str, container_path: str) -> None:
        """Copies file to container."""

    @abstractmethod
    async def read_file(self, path: str) -> str:
        """Reads file."""

    @abstractmethod
    async def write_file(self, path: str, content: str) -> None:
        """Writes file."""

    @abstractmethod
    async def cleanup(self) -> None:
        """Cleans up resources."""


class DaytonaSandboxClient(BaseSandboxClient):
    """Daytona sandbox client implementation using Daytona SDK."""

    def __init__(self) -> None:
        self.sandbox: Optional[Any] = None
        self._daytona: Optional[Any] = None
        self._work_dir: Optional[str] = None
        self._conversation_id: Optional[str] = None

    def _map_to_workspace(self, path: str) -> str:
        """Map host absolute path to Daytona workspace absolute path under work_dir."""
        if not path:
            return path
        # Already a POSIX-like path; normalize slashes
        p_str = str(path)
        # If the path already starts with work_dir, keep it
        work_dir = self._work_dir or config.sandbox.work_dir
        if p_str.replace("\\", "/").startswith(work_dir.rstrip("/")):
            return p_str.replace("\\", "/")
        try:
            host_path = Path(p_str)
            if host_path.is_absolute():
                rel = host_path.relative_to(config.workspace_root)
                mapped = Path(work_dir) / Path(str(rel).replace("\\", "/"))
                return str(mapped).replace("\\", "/")
        except Exception:
            # If cannot map, default to assuming path is already in sandbox
            return p_str.replace("\\", "/")
        return p_str.replace("\\", "/")

    async def create(
        self,
        config: Optional[SandboxSettings] = None,
        volume_bindings: Optional[Dict[str, str]] = None,
        conversation_id: Optional[str] = None,
    ) -> None:
        # Lazy import to avoid hard dependency when not used
        try:
            from daytona import Daytona, DaytonaConfig  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                f"Daytona SDK is required for 'daytona' provider but not available: {e}"
            )

        cfg = config or SandboxSettings(
            use_sandbox=True,
            provider="daytona",
            image="python:3.12-slim",
            work_dir="/workspace",
            memory_limit="512m",
            cpu_limit=1.0,
            timeout=300,
            network_enabled=True,
        )
        # Prefer environment variables when available; fall back to cfg values
        api_key = cfg.api_key or os.getenv("DAYTONA_API_KEY")
        api_url = getattr(cfg, "api_url", None) or os.getenv("DAYTONA_API_URL")
        target = getattr(cfg, "target", None) or os.getenv("DAYTONA_TARGET")
        dcfg = DaytonaConfig(
            api_key=api_key,
            api_url=api_url,
            target=target,
        )
        self._daytona = Daytona(dcfg)
        assert self._daytona is not None
        # Create sandbox (use defaults per SDK quick start)
        self.sandbox = self._daytona.create()
        # Keep configured work dir for path mapping only (do not enforce as cwd)
        self._work_dir = cfg.work_dir or "/workspace"
        # Track current conversation for potential per-conversation behavior; preserve if None
        if conversation_id is not None:
            self._conversation_id = conversation_id

    async def run_command(self, command: str, timeout: Optional[int] = None) -> str:
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")

        # Prefer capturing stdout from Daytona when supported
        try:
            response = self.sandbox.process.exec(
                command, timeout=timeout, capture_output=True
            )
        except TypeError:
            # Signature without capture_output or timeout
            try:
                response = self.sandbox.process.exec(command, timeout=timeout)
            except TypeError:
                response = self.sandbox.process.exec(command)
        except Exception:
            # Minimal invocation on unexpected SDK errors
            response = self.sandbox.process.exec(command)

        # Extract stdout/result robustly
        out = ""
        try:
            artifacts = getattr(response, "artifacts", None)
            if artifacts is not None:
                stdout_val = getattr(artifacts, "stdout", None)
                if stdout_val:
                    out = stdout_val
        except Exception:
            pass

        if not out:
            for attr in ("result", "stdout", "output"):
                if hasattr(response, attr):
                    val = getattr(response, attr)
                    if val:
                        if isinstance(val, (bytes, bytearray)):
                            out = val.decode("utf-8", "ignore")
                        else:
                            out = str(val)
                        break

        return out or ""

    async def copy_from(self, container_path: str, local_path: str) -> None:
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        spath = self._map_to_workspace(container_path)
        content = self.sandbox.fs.download_file(spath)
        if hasattr(content, "__await__"):
            content = await content
        data = content if isinstance(content, (bytes, bytearray)) else str(content).encode("utf-8")
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        Path(local_path).write_bytes(data)

    async def copy_to(self, local_path: str, container_path: str) -> None:
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        spath = self._map_to_workspace(container_path)
        data = Path(local_path).read_bytes()
        # Handle possible SDK signature differences by trying both orders
        try:
            result = self.sandbox.fs.upload_file(data, spath)
        except TypeError:
            result = self.sandbox.fs.upload_file(spath, data)
        if hasattr(result, "__await__"):
            await result

    async def read_file(self, path: str) -> str:
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        spath = self._map_to_workspace(path)
        try:
            content = self.sandbox.fs.download_file(spath)
            if hasattr(content, "__await__"):
                content = await content
            return content.decode("utf-8") if isinstance(content, (bytes, bytearray)) else str(content)
        except Exception:
            # Fallback to shell cat when SDK file API is unavailable
            out = await self.run_command(f"cat {shlex.quote(spath)} || true")
            return out

    async def write_file(self, path: str, content: str) -> None:
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        spath = self._map_to_workspace(path)
        # Ensure parent dir exists
        parent_dir = "/".join(spath.split("/")[:-1]) or self._work_dir
        await self.run_command(f"mkdir -p {shlex.quote(parent_dir)}")
        data = content.encode("utf-8")
        # Try Daytona SDK first
        try:
            try:
                result = self.sandbox.fs.upload_file(data, spath)
            except TypeError:
                result = self.sandbox.fs.upload_file(spath, data)
            if hasattr(result, "__await__"):
                await result
            return
        except Exception:
            # Fallback: write via base64 through the shell to avoid bulk-upload endpoint issues
            b64 = base64.b64encode(data).decode("ascii")
            cmd = f"echo {shlex.quote(b64)} | base64 -d > {shlex.quote(spath)}"
            await self.run_command(cmd)

    async def cleanup(self) -> None:
        if self.sandbox and self._daytona:
            try:
                # Prefer deleting via client for proper cleanup
                self._daytona.delete(self.sandbox)
            except Exception:
                pass
        self.sandbox = None
        self._daytona = None


def create_sandbox_client() -> BaseSandboxClient:
    """Creates a sandbox client; Daytona is the only supported provider now."""
    return DaytonaSandboxClient()


SANDBOX_CLIENT = create_sandbox_client()
