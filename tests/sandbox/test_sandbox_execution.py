import asyncio
import io
import json
import os
import shlex
from typing import Dict, Optional

import pytest

from app.config import config
from app.tool.file_operators import SandboxFileOperator
from app.tool.str_replace_editor import StrReplaceEditor
from app.tool.python_execute import PythonExecute
from app.tool.bash import Bash
from app.tool.tool_collection import ToolCollection


class FakeSandboxClient:
    """Minimal in-memory fake for SANDBOX_CLIENT to support tests without Daytona."""

    def __init__(self):
        self.sandbox = None
        self._work_dir: str = config.sandbox.work_dir
        # in-memory fs
        self.files: Dict[str, bytes] = {}
        self.dirs: set[str] = set()
        # seed with work_dir
        self._ensure_dir(self._work_dir)

    # utilities
    def _posix(self, p: str) -> str:
        return p.replace("\\", "/")

    def _ensure_dir(self, d: str):
        d = self._posix(d).rstrip("/")
        if not d:
            return
        parts = d.split("/")
        cur = ""
        for part in parts:
            if part == "":
                cur = "/"
                self.dirs.add(cur)
                continue
            cur = (cur.rstrip("/") + "/" + part).replace("//", "/")
            self.dirs.add(cur)

    def _parent_dir(self, p: str) -> str:
        p = self._posix(p)
        if "/" not in p.rstrip("/"):
            return "/"
        return "/".join(p.rstrip("/").split("/")[:-1]) or "/"

    # API surfaced in production client
    async def create(self, config=None, conversation_id: Optional[str] = None):
        self.sandbox = object()
        self._work_dir = (config.work_dir if config and getattr(config, "work_dir", None) else self._work_dir)
        self._ensure_dir(self._work_dir)

    async def run_command(self, cmd: str, timeout: Optional[int] = None) -> str:
        # handle test -d / test -e
        cmd_str = cmd.strip()
        # naive parse for test -d/-e
        if cmd_str.startswith("test -d ") and "&& echo" in cmd_str:
            path = cmd_str[len("test -d ") :].split("&&", 1)[0].strip().strip("'\"")
            return "true" if self._posix(path) in self.dirs else "false"
        if cmd_str.startswith("test -e ") and "&& echo" in cmd_str:
            path = cmd_str[len("test -e ") :].split("&&", 1)[0].strip().strip("'\"")
            p = self._posix(path)
            return "true" if p in self.dirs or p in self.files else "false"
        # handle find DIR -maxdepth 2 ... (very simplified)
        if cmd_str.startswith("find "):
            # extract base path
            try:
                _parts = shlex.split(cmd_str)
                base = _parts[1]
            except Exception:
                base = self._work_dir
            base = self._posix(base.rstrip("/"))
            out = []
            # include base itself
            if base:
                out.append(base)
            # list dirs/files up to depth 2 from base
            def depth(p: str) -> int:
                return len([seg for seg in p.split("/") if seg])
            base_depth = depth(base)
            # iterate
            for d in sorted(self.dirs):
                if d == base:
                    continue
                if d.startswith(base + "/") and depth(d) - base_depth <= 2:
                    out.append(d)
            for f in sorted(self.files):
                if f.startswith(base + "/") and depth(f) - base_depth <= 2:
                    out.append(f)
            return "\n".join(out)
        # handle echo
        if cmd_str.startswith("echo "):
            try:
                return shlex.split(cmd_str, posix=True)[1]
            except Exception:
                return cmd_str[5:]
        # handle cat fallback
        if cmd_str.startswith("cat "):
            path = cmd_str[len("cat ") :].split(" ")[0].strip()
            p = self._posix(path)
            data = self.files.get(p)
            return (data or b"").decode("utf-8")
        return ""

    async def write_file(self, path: str, content: str) -> None:
        p = self._posix(path)
        parent = self._parent_dir(p)
        self._ensure_dir(parent)
        self.files[p] = content.encode("utf-8")

    async def read_file(self, path: str) -> str:
        p = self._posix(path)
        if p not in self.files:
            raise FileNotFoundError(p)
        return self.files[p].decode("utf-8")

    async def code_run(self, code: str, timeout: Optional[int] = None) -> str:
        # Execute simple code capturing prints
        import sys
        import contextlib

        buf = io.StringIO()
        glb = {"__name__": "__main__"}
        try:
            with contextlib.redirect_stdout(buf):
                exec(code, glb, None)
        except Exception as e:
            return f"Traceback (most recent call last): {e}"
        return buf.getvalue()


@pytest.fixture()
def fake_sandbox(monkeypatch):
    fake = FakeSandboxClient()
    # Patch module-level SANDBOX_CLIENT usages
    import app.sandbox.client as sandbox_client_mod
    import app.tool.file_operators as fops_mod
    import app.tool.python_execute as pyexec_mod
    import app.tool.str_replace_editor as editor_mod
    import app.tool.bash as bash_mod

    monkeypatch.setattr(sandbox_client_mod, "SANDBOX_CLIENT", fake, raising=True)
    monkeypatch.setattr(fops_mod, "SANDBOX_CLIENT", fake, raising=True)
    monkeypatch.setattr(pyexec_mod, "SANDBOX_CLIENT", fake, raising=True)
    monkeypatch.setattr(bash_mod, "SANDBOX_CLIENT", fake, raising=True)
    # Also update any pre-instantiated operator in StrReplaceEditor
    editor_mod.StrReplaceEditor._sandbox_operator.sandbox_client = fake
    return fake


@pytest.mark.asyncio
async def test_sandbox_file_write_read_exists_isdir(fake_sandbox):
    op = SandboxFileOperator()
    # ensure this operator uses the fake client
    op.sandbox_client = fake_sandbox

    # Initialize sandbox
    await fake_sandbox.create(config=config.sandbox)

    # Write file and verify
    await op.write_file("/workspace/hello.txt", "Hello World")
    assert await op.exists("/workspace/hello.txt") is True
    assert await op.is_directory("/workspace") is True

    content = await op.read_file("/workspace/hello.txt")
    assert content == "Hello World"


@pytest.mark.asyncio
async def test_path_mapping_shorthand_root(fake_sandbox):
    op = SandboxFileOperator()
    op.sandbox_client = fake_sandbox

    await fake_sandbox.create(config=config.sandbox)

    # Write using shorthand '/file.txt' which should map into work_dir
    await op.write_file("/file1.txt", "A")
    # Read via fully qualified work_dir path
    fq = f"{config.sandbox.work_dir.rstrip('/')}/file1.txt"
    content = await op.read_file(fq)
    assert content == "A"


@pytest.mark.asyncio
async def test_operator_run_command_echo(fake_sandbox):
    op = SandboxFileOperator()
    op.sandbox_client = fake_sandbox

    await fake_sandbox.create(config=config.sandbox)

    code, out, err = await op.run_command("echo hello")
    assert code == 0
    assert out == "hello"
    assert err == ""


@pytest.mark.asyncio
async def test_str_replace_editor_view_file_and_directory(fake_sandbox):
    # Prepare FS
    op = SandboxFileOperator()
    op.sandbox_client = fake_sandbox
    await fake_sandbox.create(config=config.sandbox)

    text = "\n".join([f"line {i}" for i in range(1, 7)])
    await op.write_file("/workspace/readme.txt", text)
    await op.write_file("/workspace/sub/note.txt", "note")

    # View file with range
    editor = StrReplaceEditor()
    editor._sandbox_operator.sandbox_client = fake_sandbox
    out = await editor.execute(command="view", path="/workspace/readme.txt", view_range=[2, 3])
    # Should include only lines 2..3 in the cat -n output
    assert "\tline 2" in out and "\tline 3" in out
    assert "\tline 1" not in out and "\tline 4" not in out

    # View directory
    dir_out = await editor.execute(command="view", path="/workspace")
    assert "Here's the files and directories up to 2 levels deep in /workspace" in dir_out
    assert "/workspace/readme.txt" in dir_out
    assert "/workspace/sub" in dir_out


@pytest.mark.asyncio
async def test_python_execute_success_and_windows_path_rejection(fake_sandbox):
    tool = PythonExecute()

    # success path
    res = await tool.execute(code="print('OK')", timeout=5)
    assert res.status == "success"
    assert res.output.strip() == "OK"

    # windows path rejection
    res2 = await tool.execute(code="open('C\\\\\\\\temp\\\\x.txt','w')\nprint('done')", timeout=5)
    assert res2.status == "error"
    assert "Do NOT use host OS paths" in (res2.error or "")


@pytest.mark.asyncio
async def test_code_execution_shell_route_to_run_command(fake_sandbox):
    tool = PythonExecute()

    # Should detect as shell and route to SANDBOX_CLIENT.run_command
    res = await tool.execute(code="echo hello", timeout=5)
    assert res.status == "success"
    assert (res.output or "").strip() == "hello"


@pytest.mark.asyncio
async def test_code_execution_fallback_to_run_command_when_code_run_fails(fake_sandbox, monkeypatch):
    tool = PythonExecute()

    # Force code_run to fail to trigger fallback path
    async def _raise(*args, **kwargs):
        raise RuntimeError("code_run failed")

    monkeypatch.setattr(fake_sandbox, "code_run", _raise, raising=True)

    res = await tool.execute(code="print('X')", timeout=5)
    # Fallback uses run_command to run python3 /workspace/.tmp_code_exec.py which returns
    # empty output in FakeSandboxClient; success means fallback path engaged without exception.
    assert res.status == "success"


@pytest.mark.asyncio
async def test_typescript_execution_path_success(fake_sandbox):
    tool = PythonExecute()
    res = await tool.execute(code="console.log('TS')", language="typescript", timeout=5)
    # In fake sandbox, run_command returns empty string but call should be successful
    assert res.status == "success"


@pytest.mark.asyncio
async def test_code_execution_shell_guardrail_various(fake_sandbox):
    tool = PythonExecute()
    for cmd in ["ls", "npm -v", "git --version"]:
        res = await tool.execute(code=cmd, timeout=5)
        assert res.status == "success"


def test_tool_collection_maps_names_correctly():
    coll = ToolCollection(PythonExecute(), StrReplaceEditor(), Bash())
    t1 = coll.get_tool("code_execution")
    t2 = coll.get_tool("file_editor")
    t3 = coll.get_tool("bash")

    assert t1 is not None and isinstance(t1, PythonExecute)
    assert t2 is not None and isinstance(t2, StrReplaceEditor)
    assert t3 is not None and isinstance(t3, Bash)


@pytest.mark.asyncio
async def test_bash_execute_echo_and_restart(fake_sandbox):
    bash = Bash()

    # Basic echo
    rst = await bash.execute(command="echo hi", timeout=5)
    assert (rst.output or "").strip() == "hi"

    # Restart session; message should be present
    rst2 = await bash.execute(command="", restart=True)
    assert (rst2.system or "").lower().find("restarted") != -1

    # After restart, echo still works
    rst3 = await bash.execute(command="echo hi2", timeout=5)
    assert (rst3.output or "").strip() == "hi2"