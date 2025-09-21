import io
import shlex
from typing import Dict, Optional

import pytest

from app.config import config
from app.tool.file_operators import SandboxFileOperator
from app.tool.str_replace_editor import StrReplaceEditor
from app.tool.python_execute import PythonExecute
from app.tool.bash import Bash


class FakeSandboxClient:
    """Minimal in-memory fake for SANDBOX_CLIENT to support tests without Daytona.

    Extended to emulate `python3 <file>` execution for bash tests.
    """

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
        cmd_str = (cmd or "").strip()
        # handle test -d / test -e
        if cmd_str.startswith("test -d ") and "&& echo" in cmd_str:
            path = cmd_str[len("test -d ") :].split("&&", 1)[0].strip().strip("'\"")
            return "true" if self._posix(path) in self.dirs else "false"
        if cmd_str.startswith("test -e ") and "&& echo" in cmd_str:
            path = cmd_str[len("test -e ") :].split("&&", 1)[0].strip().strip("'\"")
            p = self._posix(path)
            return "true" if p in self.dirs or p in self.files else "false"
        # emulate minimal `find`
        if cmd_str.startswith("find "):
            try:
                _parts = shlex.split(cmd_str)
                base = _parts[1]
            except Exception:
                base = self._work_dir
            base = self._posix(base.rstrip("/"))
            out = []
            if base:
                out.append(base)
            def depth(p: str) -> int:
                return len([seg for seg in p.split("/") if seg])
            base_depth = depth(base)
            for d in sorted(self.dirs):
                if d == base:
                    continue
                if d.startswith(base + "/") and depth(d) - base_depth <= 2:
                    out.append(d)
            for f in sorted(self.files):
                if f.startswith(base + "/") and depth(f) - base_depth <= 2:
                    out.append(f)
            return "\n".join(out)
        # echo passthrough
        if cmd_str.startswith("echo "):
            try:
                return shlex.split(cmd_str, posix=True)[1]
            except Exception:
                return cmd_str[5:]
        # emulate python3 <file>
        if cmd_str.startswith("python3 ") or cmd_str.startswith("python "):
            try:
                parts = shlex.split(cmd_str, posix=True)
                path = parts[1]
            except Exception:
                return ""
            p = self._posix(path)
            data = self.files.get(p)
            if data is None:
                return ""
            code = data.decode("utf-8")
            import contextlib, sys
            buf = io.StringIO()
            glb = {"__name__": "__main__"}
            try:
                with contextlib.redirect_stdout(buf):
                    exec(code, glb, None)
            except Exception as e:
                return f"Traceback (most recent call last): {e}"
            return buf.getvalue()
        # cat fallback
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
        import contextlib
        buf = io.StringIO()
        glb = {"__name__": "__main__"}
        try:
            with contextlib.redirect_stdout(buf):
                exec(code, glb, None)
        except Exception as e:
            return f"Traceback (most recent call last): {e}"
        return buf.getvalue()

    async def cleanup(self) -> None:
        self.sandbox = None
        self.files.clear()
        self.dirs.clear()
        self._ensure_dir(self._work_dir)


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
    # Ensure BaseAgent persistence hook uses the fake sandbox too
    import app.agent.base as base_mod
    monkeypatch.setattr(base_mod, "SANDBOX_CLIENT", fake, raising=True)
    return fake


@pytest.mark.asyncio
async def test_str_replace_editor_end_to_end_flow(fake_sandbox):
    # 1. init sandbox
    await fake_sandbox.create(config=config.sandbox)

    editor = StrReplaceEditor()

    # 2. create file test.py
    path = "/workspace/test.py"
    content_v1 = "print('A')\n"
    out_create = await editor.execute(command="create", path=path, file_text=content_v1)
    assert "File created successfully" in out_create

    # 3. read the created file
    out_view1 = await editor.execute(command="view", path=path)
    assert "print('A')" in out_view1

    # 4. edit content inside it (str_replace)
    out_replace = await editor.execute(command="str_replace", path=path, old_str="print('A')", new_str="print('B')")
    assert "has been edited" in out_replace

    # 5. read again
    out_view2 = await editor.execute(command="view", path=path)
    assert "print('B')" in out_view2 and "print('A')" not in out_view2

    # 6. insert random content at top
    rnd = "# inserted line\n"
    out_insert = await editor.execute(command="insert", path=path, insert_line=0, new_str=rnd)
    assert "has been edited" in out_insert

    # 7. view the file
    out_view3 = await editor.execute(command="view", path=path)
    assert "# inserted line" in out_view3 and "print('B')" in out_view3

    # 8. run test via bash tool for test.py (python3 execution)
    bash = Bash()
    out_bash = await bash.execute(command=f"python3 {path}")
    assert out_bash.status == "success"
    # Should print B once
    assert (out_bash.output or "").strip().splitlines()[-1] == "B"

    # 9. run test via code_execution tool for the file content
    op = SandboxFileOperator()
    op.sandbox_client = fake_sandbox
    file_code = await op.read_file(path)
    pyexec = PythonExecute()
    out_exec = await pyexec.execute(code=file_code)
    assert out_exec.status == "success"
    assert (out_exec.output or "").strip().splitlines()[-1] == "B"


@pytest.mark.asyncio
async def test_wrong_paths_handling_and_mapping(fake_sandbox):
    await fake_sandbox.create(config=config.sandbox)
    editor = StrReplaceEditor()
    op = SandboxFileOperator()
    op.sandbox_client = fake_sandbox

    # 1) Windows absolute path maps under work_dir with basename
    win_path = r"C:\\temp\\test2.py"
    out_create = await editor.execute(command="create", path=win_path, file_text="print('X')\n")
    assert "File created successfully" in out_create
    # Verify actual stored path is work_dir/basename
    mapped = op.to_sandbox_path(win_path)
    assert mapped.endswith("/test2.py")
    assert await op.exists(mapped) is True

    # 2) POSIX absolute outside work_dir should be relocated under work_dir
    posix_outside = "/etc/app.py"
    out_create2 = await editor.execute(command="create", path=posix_outside, file_text="print('Y')\n")
    assert "File created successfully" in out_create2
    mapped2 = op.to_sandbox_path(posix_outside)
    assert mapped2.startswith(config.sandbox.work_dir.rstrip("/") + "/")
    assert await op.exists(mapped2) is True

    # 3) Relative path maps under work_dir preserving directories
    rel_path = "nested/dir/sample.py"
    out_create3 = await editor.execute(command="create", path=rel_path, file_text="print('Z')\n")
    assert "File created successfully" in out_create3
    mapped3 = op.to_sandbox_path(rel_path)
    assert mapped3.startswith(config.sandbox.work_dir.rstrip("/") + "/nested/dir/")
    assert await op.exists(mapped3) is True

    # 4) View non-existent path raises error via underlying read_file
    with pytest.raises(Exception):
        await editor.execute(command="view", path="/workspace/not_exists.py")

    # 5) Using directory path for str_replace should error (cannot read directory)
    # Prepare a directory path
    dir_path = f"{config.sandbox.work_dir.rstrip('/')}/adir"
    # ensure directory exists in fake sandbox
    fake_sandbox._ensure_dir(dir_path)
    with pytest.raises(Exception):
        await editor.execute(command="str_replace", path=dir_path, old_str="foo", new_str="bar")


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_file_editor_create_persists_file_artifact(fake_sandbox):
    import asyncio
    from django.contrib.auth import get_user_model
    from app.models import Conversation, FileArtifact
    from app.agent.manus import Manus

    User = get_user_model()
    user = await User.objects.acreate(username="tester_persist")

    conv = await Conversation.objects.acreate(user=user, title="t")

    # Init sandbox
    await fake_sandbox.create(config=config.sandbox)

    # Create agent with persistence attached
    agent = await Manus.create(conversation_id=str(conv.id))

    # Prepare editor with agent context
    editor = StrReplaceEditor()
    editor.agent = agent

    path = "/workspace/new.txt"
    content = "hello world"

    # Execute create command
    out = await editor.execute(command="create", path=path, file_text=content)
    assert "File created successfully" in out

    # Wait for background persist tasks to complete
    if getattr(agent, "pending_persist_tasks", None):
        pending = [t for t in agent.pending_persist_tasks if not t.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            agent.pending_persist_tasks.clear()

    # Compute mapped path as persisted by hook
    op = SandboxFileOperator()
    op.sandbox_client = fake_sandbox
    mapped = op.to_sandbox_path(path)

    # Verify FileArtifact created
    artifacts = []
    async for fa in FileArtifact.objects.filter(conversation=conv, path=mapped):
        artifacts.append(fa)

    assert len(artifacts) == 1
    assert artifacts[0].filename.endswith("new.txt")
    assert artifacts[0].stored_content.strip() == content