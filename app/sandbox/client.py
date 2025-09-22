from abc import ABC, abstractmethod
from typing import Dict, Optional, Protocol, Any

from app.config import SandboxSettings, config
from pathlib import Path
import os
import uuid
import base64
import shlex
import asyncio
from app.logger import logger


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
        conversation_id: Optional[str] = None,
    ) -> None:
        """Creates sandbox."""

    @abstractmethod
    async def run_command(self, command: str, timeout: Optional[int] = None, env: Optional[Dict[str, str]] = None) -> str:
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
        # Track which conversation the current sandbox was actually created for
        self._sandbox_conv_id: Optional[str] = None

    def _map_to_workspace(self, path: str) -> str:
        """Map any incoming path to a POSIX path within the sandbox work_dir.

        Rules:
        - If already starts with work_dir (e.g. '/workspace'), keep as is.
        - If starts with '/' but not with work_dir, treat as inside work_dir (e.g. '/file.py' -> '/workspace/file.py').
        - If it's an absolute host path (Windows/Unix), try to map relative to config.workspace_root; if not possible, place under work_dir with basename.
        - For relative paths, treat as relative to work_dir.
        """
        if not path:
            return path
        p_str = str(path)
        work_dir = (self._work_dir or (config.sandbox.work_dir if config.sandbox else "/home/daytona/workspace") or "/home/daytona/workspace").rstrip("/")
        posix = p_str.replace("\\", "/")

        # Already in sandbox workspace
        if posix == work_dir or posix.startswith(work_dir + "/"):
            return posix

        # Legacy paths like '/workspace/...': rewrite to configured work_dir to avoid duplication
        if posix == "/workspace" or posix.startswith("/workspace/"):
            remainder = posix[len("/workspace"):].lstrip("/")
            return work_dir if not remainder else f"{work_dir}/{remainder}"

        # POSIX absolute but outside work_dir -> relocate into work_dir
        if posix.startswith("/"):
            return f"{work_dir}/{posix.lstrip('/')}"

        # Host absolute paths (Windows/Unix)
        try:
            host_path = Path(p_str)
            if host_path.is_absolute():
                ws_root_val = getattr(config, "workspace_root", None)
                ws_root = Path(ws_root_val) if ws_root_val else None
                if ws_root:
                    try:
                        rel = host_path.relative_to(ws_root)
                        return f"{work_dir}/{rel.as_posix()}"
                    except Exception:
                        pass
                # Fallback: use basename under work_dir to avoid leaking host paths
                return f"{work_dir}/{host_path.name}"
        except Exception:
            pass

        # Relative path -> treat as under work_dir
        return f"{work_dir}/{posix}"

    async def create(
        self,
        config: Optional[SandboxSettings] = None,
        conversation_id: Optional[str] = None,
    ) -> None:
        # Lazy import to avoid hard dependency when not used
        try:
            from daytona import Daytona, DaytonaConfig  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                f"Daytona SDK is required for 'daytona' provider but not available: {e}"
            )
        logger.info(f"Creating sandbox with config: {config}")
        cfg = config or SandboxSettings(
            use_sandbox=True,
            provider="daytona",
            image="python:3.12-slim",
            work_dir="/home/daytona/workspace",
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
        # set conversation context early for later helpers
        # Fallback to existing attribute if param not provided
        conv_id = conversation_id or getattr(self, "_conversation_id", None)
        self._conversation_id = conv_id

        # Decide mount dir upfront
        mount_dir = cfg.work_dir or "/home/daytona/workspace"

        # Try to create sandbox with an existing or freshly created conversation volume
        created_with_volume = False
        conv = None
        conv_volume_id = None
        conv_volume_name = None
        if conv_id:
            try:
                # Fetch conversation and known volume info
                from app.models import Conversation
                conv = await Conversation.objects.aget(id=conv_id)
                conv_volume_id = getattr(conv, "daytona_volume_id", None)
                conv_volume_name = getattr(conv, "daytona_volume_name", None) or f"manus-{conv_id}"

                # Ensure a volume exists if id missing: get or create by name
                if not conv_volume_id:
                    try:
                        volume = self._daytona.volume.get(conv_volume_name, create=True)
                        conv_volume_id = str(getattr(volume, "id", None) or getattr(volume, "uuid", None) or "") or None
                        conv_volume_name = str(getattr(volume, "name", None) or "") or None
                        logger.info(f"Created volume persistant. volume id: {conv_volume_id}. volume name: {conv_volume_name}")

                        # Wait for volume to become ready before attempting to mount
                        try:
                            max_wait = int(os.getenv("DAYTONA_VOLUME_READY_TIMEOUT", "60"))
                            poll_interval = float(os.getenv("DAYTONA_VOLUME_POLL_INTERVAL", "1"))
                            waited = 0.0
                            while waited < max_wait:
                                try:
                                    v = self._daytona.volume.get(conv_volume_name, create=False)
                                    v_state = str(getattr(v, "status", None) or getattr(v, "state", None) or "").lower()
                                    if v_state in ("", "ready", "available", "active", "created", "success", "ok"):
                                        break
                                    logger.info(f"Daytona volume '{conv_volume_name}' not ready yet (state={v_state}); waiting...")
                                except Exception as _e:
                                    logger.warning(f"Failed to query Daytona volume state while waiting: {_e}")
                                    # Best-effort; continue polling a bit longer
                                await asyncio.sleep(poll_interval)
                                waited += poll_interval
                        except Exception as _e:
                            logger.warning(f"Volume readiness wait skipped due to error: {_e}")

                        if conv_volume_id:
                            try:
                                from asgiref.sync import sync_to_async
                                conv.daytona_volume_id = conv_volume_id
                                conv.daytona_volume_name = conv_volume_name
                                await sync_to_async(conv.save)(update_fields=["daytona_volume_id", "daytona_volume_name"])
                            except Exception as e:
                                logger.warning(f"Failed to persist conversation Daytona volume id/name: {e}")
                    except Exception as e:
                        logger.warning(f"Daytona volume.get(create=True) failed; will continue without pre-fetched id: {e}")

                # First attempt: create sandbox mounting the known volume id
                try:
                    from daytona import CreateSandboxFromSnapshotParams, VolumeMount  # type: ignore
                    params = CreateSandboxFromSnapshotParams(
                        volumes=[VolumeMount(volumeId=conv_volume_id, mountPath=mount_dir)],
                    )
                    self.sandbox = self._daytona.create(params)
                    logger.info(f"sandbox created: {self.sandbox}")
                    created_with_volume = True
                    logger.info(
                        f"DaytonaSandboxClient.create: mounted existing volume for conversation={conv_id}, volume_id={conv_volume_id}, mount_dir={mount_dir}"
                    )
                except Exception as e:
                    logger.warning(f"Create with existing volume failed, will try creating a new volume: {e}")
                    # Second attempt can be implemented here if desired
                        # Second attempt: create a brand new volume and mount
            except Exception as e:
                logger.warning(f"Daytona volume mounting path failed entirely; will proceed without volume: {e}")

        # If volume mounting didn't work, create sandbox without volume and optionally sync initial artifacts
        if not created_with_volume:
            try:
                # Fallback: simple sandbox creation without explicit volume mounts

                self.sandbox = self._daytona.create()
                logger.info("DaytonaSandboxClient.create: created sandbox without mounted volume; will sync artifacts if any")
            except Exception as e:
                raise RuntimeError(f"Failed to create Daytona sandbox: {e}")

        # Ensure work_dir exists and is set on client
        self._work_dir = cfg.work_dir or "/home/daytona/workspace"
        try:
            logger.info(f"try creating working dir {self._work_dir}")
            await self.run_command(f"mkdir -p {shlex.quote(self._work_dir)} && chmod -R 777 {shlex.quote(self._work_dir)}")
        except Exception as e:
            logger.warning(f"Failed to prepare work_dir in sandbox: {e}")

        # If no volume mount was used, sync any existing FileArtifact contents into sandbox
        try:
            if not created_with_volume and conv_id:
                logger.info(f"No Volume in sandbox, try to syncing artifacts for conversation to sandbox: {conv_id}")
                from app.models import FileArtifact
                from asgiref.sync import sync_to_async
                # Filter by Conversation UUID field, not PK, to avoid pkid type mismatch
                qs = FileArtifact.objects.filter(conversation__id=conv_id).only("path", "stored_content")
                artifacts = await sync_to_async(list)(qs)
                logger.info(f"syncing {len(artifacts)} artifacts for conversation {conv_id} to sandbox")
                if artifacts:
                    for fa in artifacts:
                        path = getattr(fa, "path", None)
                        data = getattr(fa, "stored_content", None)
                        if path and data:
                            # Map path to workspace dir to keep consistency
                            spath = self._map_to_workspace(str(path))
                            try:
                                await self.write_file(spath, str(data))
                            except Exception as e:
                                logger.warning(f"Failed to seed artifact into sandbox: {path}: {e}")
        except Exception as e:
            # Non-fatal if ORM not ready
            logger.info(f"No artifacts to seed or failed to seed due to: {e}")
        # Record the conversation id this sandbox is associated with
        self._sandbox_conv_id = conv_id

    async def run_command(self, command: str, timeout: Optional[int] = None, env: Optional[Dict[str, str]] = None) -> str:
        """Execute a shell command in the sandbox, anchored to the configured work_dir.

        It uses Daytona SDK's process.exec with cwd set to the globally initialized
        workspace directory, and includes a robust fallback that prefixes `cd <cwd> &&`.
        """
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        if command is None:
            return ""
        cwd = (self._work_dir or (config.sandbox.work_dir if config.sandbox else "/home/daytona/workspace") or "/home/daytona/workspace")

        # Helper: build shell exports for env when falling back
        def _export_env_prefix(e: Optional[Dict[str, str]]) -> str:
            if not e:
                return ""
            parts = []
            for k, v in e.items():
                # Only allow safe env var names
                if not k or not isinstance(k, str):
                    continue
                if not __import__('re').match(r"^[A-Za-z_][A-Za-z0-9_]*$", k):
                    continue
                parts.append(f"export {k}={shlex.quote(str(v))}")
            return ("; ".join(parts) + "; ") if parts else ""

        # Primary attempt: use Daytona process.exec with cwd/timeout/env
        try:
            try:
                resp = self.sandbox.process.exec(command, cwd=cwd, timeout=timeout)
            except TypeError:
                # Older SDKs may not support env/cwd; try progressively with supported args
                try:
                    resp = self.sandbox.process.exec(command, cwd=cwd, timeout=timeout)
                except TypeError:
                    resp = self.sandbox.process.exec(command, timeout=timeout)
            if hasattr(resp, "__await__"):
                resp = await resp
            # Extract result from common attributes
            result = None
            for attr in ("result", "stdout", "output"):
                if hasattr(resp, attr):
                    result = getattr(resp, attr)
                    break
            if isinstance(result, (bytes, bytearray)):
                return result.decode("utf-8", errors="ignore")
            if isinstance(result, str):
                return result
            # Fallback to stringifying response
            return "" if resp is None else str(resp)
        except Exception:
            # Secondary attempt: enforce cwd/env via shell
            try:
                exports = _export_env_prefix(env)
                fallback_cmd = f"{exports}cd {shlex.quote(cwd)} && {command}"
                resp2 = self.sandbox.process.exec(fallback_cmd, timeout=timeout)
                if hasattr(resp2, "__await__"):
                    resp2 = await resp2
                result2 = None
                for attr in ("result", "stdout", "output"):
                    if hasattr(resp2, attr):
                        result2 = getattr(resp2, attr)
                        break
                if isinstance(result2, (bytes, bytearray)):
                    return result2.decode("utf-8", errors="ignore")
                if isinstance(result2, str):
                    return result2
                return "" if resp2 is None else str(resp2)
            except Exception as e2:
                raise RuntimeError(f"Failed to execute command in sandbox (cwd={cwd}): {command}. Error: {e2}") from e2

    async def code_run(self, code: str, timeout: Optional[int] = None) -> str:
        """Run Python code directly inside the sandbox via Daytona's code_run API.

        - Prefer SDK process.code_run with cwd bound to the configured work_dir when supported.
        - Fallback to writing a temp file and executing it with python3/python via run_command.
        """
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        cwd = (self._work_dir or (config.sandbox.work_dir if config.sandbox else "/home/daytona/workspace") or "/home/daytona/workspace")
        # Primary: use SDK code_run
        try:
            try:
                resp = self.sandbox.process.code_run(code, timeout=timeout)
            except TypeError:
                # Some SDK versions might not support cwd param for code_run
                resp = self.sandbox.process.code_run(code, timeout=timeout)
            if hasattr(resp, "__await__"):
                resp = await resp
            result = None
            for attr in ("result", "stdout", "output"):
                if hasattr(resp, attr):
                    result = getattr(resp, attr)
                    break
            if isinstance(result, (bytes, bytearray)):
                return result.decode("utf-8", errors="ignore")
            if isinstance(result, str):
                return result
            return "" if resp is None else str(resp)
        except Exception:
            # Fallback: write to a temporary file and execute via python
            import time as _time
            work_dir = cwd.rstrip("/")
            conv = getattr(self, "_conversation_id", None)
            tmp_base = f"{work_dir}/.manus_tmp" if not conv else f"{work_dir}/.manus/{conv}/tmp"
            await self.run_command(f"mkdir -p {shlex.quote(tmp_base)}")
            filename = f"{tmp_base}/exec_{int(_time.time()*1000)}.py"
            await self.write_file(filename, code)
            cmd = f"python3 {filename} 2>&1 || python {filename} 2>&1"
            return await self.run_command(cmd, timeout=timeout)

    async def copy_from(self, container_path: str, local_path: str) -> None:
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        spath = self._map_to_workspace(container_path)
        # Ensure local parent dir exists
        local_p = Path(local_path)
        local_p.parent.mkdir(parents=True, exist_ok=True)
        # Try Daytona SDK first
        try:
            content = self.sandbox.fs.download_file(spath)
            if hasattr(content, "__await__"):
                content = await content
            if isinstance(content, (bytes, bytearray)):
                data = bytes(content)
            else:
                data = str(content).encode("utf-8")
            local_p.write_bytes(data)
            return
        except Exception:
            # Fallback via shell base64 to preserve binary content
            try:
                out = await self.run_command(f"base64 {shlex.quote(spath)}")
                data = base64.b64decode(out)
                local_p.write_bytes(data)
                return
            except Exception:
                # Last resort: plain cat (may corrupt binary). Best-effort.
                out2 = await self.run_command(f"cat {shlex.quote(spath)} || true")
                try:
                    local_p.write_text(out2, encoding="utf-8")
                except Exception:
                    # If binary, ignore errors
                    pass

    async def copy_to(self, local_path: str, container_path: str) -> None:
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        spath = self._map_to_workspace(container_path)
        # Try Daytona SDK first
        try:
            data = Path(local_path).read_bytes()
            resp = self.sandbox.fs.upload_file(spath, data)
            if hasattr(resp, "__await__"):
                await resp
            return
        except Exception:
            # Fallback to base64 via shell for reliability
            data = Path(local_path).read_bytes()
            b64 = base64.b64encode(data).decode("ascii")
            await self.run_command(f"echo {shlex.quote(b64)} | base64 -d > {shlex.quote(spath)} && chmod 644 {shlex.quote(spath)}")

    async def read_file(self, path: str) -> str:
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        spath = self._map_to_workspace(path)
        # Try Daytona SDK
        try:
            content = self.sandbox.fs.read_text_file(spath)
            if hasattr(content, "__await__"):
                content = await content
            if isinstance(content, (bytes, bytearray)):
                return content.decode("utf-8", errors="ignore")
            return str(content)
        except Exception:
            # Fallback to shell
            return await self.run_command(f"cat {shlex.quote(spath)} || true")

    async def write_file(self, path: str, content: str) -> None:
        if not self.sandbox:
            raise RuntimeError("Sandbox not initialized")
        spath = self._map_to_workspace(path)
        # Try Daytona SDK
        try:
            data = content.encode("utf-8")
            resp = self.sandbox.fs.upload_file(spath, data)
            if hasattr(resp, "__await__"):
                await resp
        except Exception:
            # Fallback to shell using base64 to preserve content
            b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
            await self.run_command(f"echo {shlex.quote(b64)} | base64 -d > {shlex.quote(spath)} && chmod 644 {shlex.quote(spath)}")

        # Post-write diagnostics: existence and size
        try:
            exists_flag = await self.run_command(f"test -e {shlex.quote(spath)} && echo EXISTS || echo MISSING")
            size_info = await self.run_command(f"wc -c < {shlex.quote(spath)} || echo NA")
            logger.info(f"DaytonaSandboxClient.write_file: path={spath} exists={exists_flag.strip()} size_bytes={(size_info or '').strip()}")
        except Exception as e:
            logger.warning(f"DaytonaSandboxClient.write_file: failed to verify write for {spath}: {e}")

    async def cleanup(self) -> None:
        if self.sandbox and self._daytona:
            try:
                # Prefer deleting via client for proper cleanup
                self._daytona.delete(self.sandbox)
            except Exception:
                pass
        self.sandbox = None
        self._daytona = None
        self._sandbox_conv_id = None


def create_sandbox_client() -> BaseSandboxClient:
    """Creates a sandbox client; Daytona is the only supported provider now."""
    return DaytonaSandboxClient()


SANDBOX_CLIENT = create_sandbox_client()
