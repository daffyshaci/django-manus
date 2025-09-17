import pytest

from app.tasks import run_manus_agent


class DummyAgent:
    def __init__(self):
        self.created_with = None
        self.ran_with = None
        self.cleaned = False

    @classmethod
    async def create(cls, **kwargs):
        inst = cls()
        inst.created_with = kwargs
        return inst

    async def run(self, prompt):
        self.ran_with = prompt
        return "done"

    async def cleanup(self):
        self.cleaned = True


def test_run_manus_agent_forwards_llm_overrides(monkeypatch):
    # Arrange: replace Manus and DataAnalysis class in tasks module with DummyAgent
    import app.tasks as tasks_mod

    # monkeypatch Manus and DataAnalysis referenced in app.tasks
    monkeypatch.setattr(tasks_mod, "Manus", DummyAgent)
    monkeypatch.setattr(tasks_mod, "DataAnalysis", DummyAgent)

    captured = {}

    async def capture_create(**kwargs):
        # record kwargs and delegate to DummyAgent.create
        captured.update(kwargs)
        return await DummyAgent.create(**kwargs)

    # ensure our patched classes use the capture_create
    monkeypatch.setattr(DummyAgent, "create", classmethod(lambda cls, **kwargs: capture_create(**kwargs)))

    # Act: call the celery task's underlying run() synchronously
    overrides = {"model": "gpt-test", "temperature": 0.2}
    result = run_manus_agent.run(
        prompt="hello",
        conversation_id="1234",
        agent_kwargs={"extra": 1},
        agent_type=None,
        llm_overrides=overrides,
    )

    # Assert: task completed and llm_overrides were forwarded into Manus.create kwargs
    assert result == "done"
    # conversation_id propagated and not duplicated
    assert captured.get("conversation_id") == "1234"
    # llm_overrides propagated
    assert captured.get("llm_overrides") == overrides
    # any passthrough kwargs preserved
    assert captured.get("extra") == 1


def test_run_manus_agent_agent_type_switch(monkeypatch):
    import app.tasks as tasks_mod

    class MarkerAgent(DummyAgent):
        pass

    # Patch DataAnalysis to distinguish selection via agent_type
    monkeypatch.setattr(tasks_mod, "Manus", DummyAgent)
    monkeypatch.setattr(tasks_mod, "DataAnalysis", MarkerAgent)

    seen = {}

    async def marker_create(**kwargs):
        seen.update(kwargs)
        return await MarkerAgent.create(**kwargs)

    monkeypatch.setattr(MarkerAgent, "create", classmethod(lambda cls, **kwargs: marker_create(**kwargs)))

    res = run_manus_agent.run(
        prompt="p",
        conversation_id=None,
        agent_kwargs=None,
        agent_type="data_analysis",
        llm_overrides={"model": "gpt-da"},
    )

    assert res == "done"
    # Ensure llm_overrides passed under data_analysis path
    assert seen.get("llm_overrides", {}).get("model") == "gpt-da"