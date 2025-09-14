import pytest
import pytest_asyncio

from app.agent.toolcall import ToolCallAgent
from app.schema import ToolChoice


class HookRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, agent, role, content, base64_image, extra):
        # Record minimal info to assert later
        self.calls.append({
            "role": role,
            "content": content,
            "base64_image": base64_image,
            "extra": dict(extra or {}),
        })


@pytest_asyncio.fixture
async def agent():
    # Fresh agent per test with default config
    a = ToolCallAgent()
    return a


@pytest.mark.asyncio
async def test_update_memory_persist_flag(agent: ToolCallAgent):
    hook = HookRecorder()
    agent.persist_message_hook = hook

    # 1) Ephemeral user message should NOT trigger hook
    agent.update_memory("user", "internal-user-ephemeral", persist=False)
    assert len(agent.memory.messages) == 1
    assert agent.memory.messages[-1].role == "user"
    assert hook.calls == []  # no persistence

    # 2) Normal user message SHOULD trigger hook
    agent.update_memory("user", "real-user-input")
    assert len(agent.memory.messages) == 2
    assert agent.memory.messages[-1].role == "user"
    assert len(hook.calls) == 1
    assert hook.calls[0]["role"] == "user"
    assert hook.calls[0]["content"] == "real-user-input"


@pytest.mark.asyncio
async def test_think_injects_ephemeral_next_step_prompt(agent: ToolCallAgent):
    # Setup: next_step_prompt exists; persistence hook records any calls
    agent.next_step_prompt = "DO NOT PERSIST: internal next step"
    hook = HookRecorder()
    agent.persist_message_hook = hook

    # Mock ask_tool to avoid calling real LLM
    class DummyResp:
        def __init__(self, content: str, tool_calls=None):
            self.content = content
            self.tool_calls = tool_calls or []

    async def fake_ask_tool(**kwargs):
        return DummyResp(content="assistant-thought", tool_calls=[])

    agent.llm.ask_tool = fake_ask_tool  # type: ignore
    agent.tool_choices = ToolChoice.AUTO

    proceed = await agent.think()

    # It should proceed because assistant content is present
    assert proceed is True

    # First message: ephemeral user prompt injected
    assert len(agent.memory.messages) >= 1
    assert agent.memory.messages[0].role == "user"
    assert "internal next step" in agent.memory.messages[0].content

    # Persistence hook should NOT be called for the ephemeral user message,
    # but it SHOULD be called for the assistant message that was added later.
    # So total calls should be 1 (assistant content), not 0 and not >1
    assert len(hook.calls) == 1
    assert hook.calls[0]["role"] == "assistant"


@pytest.mark.asyncio
async def test_act_no_tool_calls_adds_ephemeral_guidance(agent: ToolCallAgent):
    hook = HookRecorder()
    agent.persist_message_hook = hook

    # Ensure there are no tool calls and it's not REQUIRED mode
    agent.tool_calls = []
    agent.tool_choices = ToolChoice.AUTO

    result = await agent.act()
    assert "Guidance added" in result

    # The internal guidance should be added as a user message in memory
    assert len(agent.memory.messages) >= 1
    assert agent.memory.messages[-1].role == "user"
    assert "does not call any tool" in agent.memory.messages[-1].content

    # But it should NOT be persisted
    assert hook.calls == []


@pytest.mark.asyncio
async def test_run_persists_real_user_message(agent: ToolCallAgent):
    hook = HookRecorder()
    agent.persist_message_hook = hook

    # Avoid entering think/act loop by setting max_steps=0
    agent.max_steps = 0

    result = await agent.run(request="Halo, ini pesan user asli")

    # run() should accept and store the user message and, by default, persist it
    assert isinstance(result, str)
    assert len(agent.memory.messages) == 1
    assert agent.memory.messages[0].role == "user"
    assert "pesan user asli" in agent.memory.messages[0].content

    # Persistence was called exactly once for the real user message
    assert len(hook.calls) == 1
    assert hook.calls[0]["role"] == "user"
    assert "pesan user asli" in hook.calls[0]["content"]