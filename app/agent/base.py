from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import List, Optional, Callable
import asyncio

from pydantic import BaseModel, Field, model_validator

from app.llm import LLM
from app.logger import logger
from app.sandbox.client import SANDBOX_CLIENT
from app.schema import ROLE_TYPE, AgentState, Memory, Message
from app.consumers.notifications import send_notification_async


class BaseAgent(BaseModel, ABC):
    """Abstract base class for managing agent state and execution.

    Provides foundational functionality for state transitions, memory management,
    and a step-based execution loop. Subclasses must implement the `step` method.
    """

    # Core attributes
    name: str = Field(..., description="Unique name of the agent")
    description: Optional[str] = Field(None, description="Optional agent description")

    # Prompts
    system_prompt: Optional[str] = Field(
        None, description="System-level instruction prompt"
    )
    next_step_prompt: Optional[str] = Field(
        None, description="Prompt for determining next action"
    )

    # Dependencies
    llm: LLM = Field(default_factory=LLM, description="Language model instance")
    memory: Memory = Field(default_factory=Memory, description="Agent's memory store")
    state: AgentState = Field(
        default=AgentState.IDLE, description="Current agent state"
    )

    # Execution control
    max_steps: int = Field(default=10, description="Maximum steps before termination")
    current_step: int = Field(default=0, description="Current step in execution")

    duplicate_threshold: int = 2

    # Context identifiers for persistence
    conversation_id: Optional[str] = Field(
        default=None,
        description="Django Conversation primary key to persist messages/memory to",
    )

    # Optional persistence hook: (agent, role, content, base64_image, kwargs_dict) -> None | awaitable
    persist_message_hook: Optional[Callable[["BaseAgent", str, str, Optional[str], dict], None]] = Field(  # type: ignore
        default=None,
        description=(
            "Optional callable invoked after update_memory to persist message to external storage. "
            "Signature: (agent, role, content, base64_image, extra_kwargs)"
        ),
    )

    # Track pending async persistence tasks to ensure they complete before run() returns
    pending_persist_tasks: List[asyncio.Task] = Field(default_factory=list, exclude=True)  # type: ignore

    class Config:
        arbitrary_types_allowed = True
        extra = "allow"  # Allow extra fields for flexibility in subclasses

    @model_validator(mode="after")
    def initialize_agent(self) -> "BaseAgent":
        """Initialize agent with default settings if not provided."""
        if self.llm is None or not isinstance(self.llm, LLM):
            self.llm = LLM(config_name=self.name.lower())
        if not isinstance(self.memory, Memory):
            self.memory = Memory()
        return self

    @asynccontextmanager
    async def state_context(self, new_state: AgentState):
        """Context manager for safe agent state transitions.

        Args:
            new_state: The state to transition to during the context.

        Yields:
            None: Allows execution within the new state.

        Raises:
            ValueError: If the new_state is invalid.
        """
        if not isinstance(new_state, AgentState):
            raise ValueError(f"Invalid state: {new_state}")

        previous_state = self.state
        self.state = new_state
        try:
            yield
        except Exception as e:
            self.state = AgentState.ERROR  # Transition to ERROR on failure
            raise e
        finally:
            self.state = previous_state  # Revert to previous state

    def update_memory(
        self,
        role: ROLE_TYPE,  # type: ignore
        content: str,
        base64_image: Optional[str] = None,
        *,
        persist: bool = True,
        **kwargs,
    ) -> None:
        """Add a message to the agent's memory and optionally persist via hook.

        Args:
            role: The role of the message sender (user, system, assistant, tool).
            content: The message content.
            base64_image: Optional base64 encoded image.
            persist: Whether to persist this message to external storage via the configured hook.
                Set to False for ephemeral messages that are only for LLM context and should not appear in the UI/DB.
            **kwargs: Additional arguments (e.g., tool_call_id, name, tool_calls).

        Raises:
            ValueError: If the role is unsupported.
        """
        message_map = {
            "user": Message.user_message,
            "system": Message.system_message,
            "assistant": Message.assistant_message,
            "tool": lambda content, **kw: Message.tool_message(content, **kw),
        }

        if role not in message_map:
            raise ValueError(f"Unsupported message role: {role}")

        # Build kwargs for message creation
        # - For tool: expect name and tool_call_id
        # - For assistant with tool_calls provided: use from_tool_calls()
        # - Others: only base64_image when provided
        msg = None
        try:
            if role == "assistant" and "tool_calls" in kwargs and kwargs["tool_calls"]:
                # Construct assistant message that includes tool_calls
                msg = Message.from_tool_calls(
                    tool_calls=kwargs["tool_calls"],
                    content=content,
                    base64_image=base64_image,
                )
            else:
                create_kwargs = {}
                if base64_image is not None:
                    create_kwargs["base64_image"] = base64_image
                if role == "tool":
                    # Pass through tool-specific fields
                    if "tool_call_id" in kwargs:
                        create_kwargs["tool_call_id"] = kwargs["tool_call_id"]
                    if "name" in kwargs:
                        create_kwargs["name"] = kwargs["name"]
                msg = message_map[role](content, **create_kwargs)
        except TypeError as e:
            # Provide more context to help debug unexpected kwargs
            logger.error(f"Error creating message for role={role}: {e}. kwargs={kwargs}")
            raise

        # Add to in-memory store first (schema memory)
        self.memory.add_message(msg)

        # Then invoke persistence hook so Django gets a consistent view
        if persist and self.persist_message_hook:
            try:
                result = self.persist_message_hook(self, role, content, base64_image, kwargs)
                # Support coroutine hooks transparently
                if hasattr(result, "__await__"):
                    # Schedule and track the task so we can await it before run() returns
                    try:
                        loop = asyncio.get_running_loop()
                        task = loop.create_task(result)  # type: ignore[arg-type]
                        self.pending_persist_tasks.append(task)
                    except RuntimeError:
                        # No running loop; run synchronously as a fallback
                        asyncio.run(result)  # type: ignore[arg-type]
            except Exception as e:
                logger.error(f"Error in persist_message_hook: {e}")

    # === Django ORM persistence helper ===
    def attach_django_persistence(self, conversation_id: str) -> None:
        """Enable Django-based persistence for messages and memory using a Conversation ID.

        This sets self.persist_message_hook to a closure that writes to app.models.Message and app.models.Memory.
        Safe to call from Celery tasks where Django has already been initialized.
        """
        self.conversation_id = str(conversation_id)

        async def _hook(agent: "BaseAgent", role: str, content: str, base64_image: Optional[str], extra: dict):
            try:
                # Lazy import to avoid Django dependency at import time
                from asgiref.sync import sync_to_async
                from app.models import Conversation as ConversationDB
                from app.models import Message as MessageDB
                from app.models import Memory as MemoryDB

                # Fetch conversation safely in async context
                conv = await sync_to_async(ConversationDB.objects.get)(id=agent.conversation_id)

                # Create ORM Message via class helpers safely
                if role == "assistant" and extra.get("tool_calls"):
                    msg_obj = await sync_to_async(MessageDB.from_tool_calls)(
                        conversation=conv,
                        tool_calls=extra.get("tool_calls") or [],
                        content=content,
                        base64_image=base64_image,
                    )
                elif role == "tool":
                    msg_obj = await sync_to_async(MessageDB.tool_message)(
                        conversation=conv,
                        content=content,
                        name=extra.get("name"),
                        tool_call_id=extra.get("tool_call_id"),
                        base64_image=base64_image,
                    )
                elif role == "system":
                    msg_obj = await sync_to_async(MessageDB.system_message)(conversation=conv, content=content)
                elif role == "user":
                    msg_obj = await sync_to_async(MessageDB.user_message)(
                        conversation=conv, content=content, base64_image=base64_image
                    )
                else:
                    msg_obj = await sync_to_async(MessageDB.assistant_message)(
                        conversation=conv, content=content, base64_image=base64_image
                    )

                # Upsert Memory for this conversation and append message JSON
                # async def _get_or_create_memory():
                #     return MemoryDB.objects.get_or_create(conversation=conv, defaults={"messages": []})

                memory, _ = await sync_to_async(MemoryDB.objects.get_or_create)(conversation=conv, defaults={"messages": []})
                await sync_to_async(memory.add_message)(msg_obj)

                # Emit WS event so frontend can append live without reload
                try:
                    payload = {
                        "id": str(msg_obj.id),
                        "conversation_id": str(conv.id),
                        "role": msg_obj.role,
                        "content": msg_obj.content,
                        "tool_calls": msg_obj.tool_calls,
                        "tool_call_id": msg_obj.tool_call_id,
                        "base64_image": msg_obj.base64_image,
                        "created_at": msg_obj.created_at.isoformat() if msg_obj.created_at else None,
                        "updated_at": msg_obj.updated_at.isoformat() if msg_obj.updated_at else None,
                    }
                    await send_notification_async(str(conv.id), "message.created", {"message": payload})
                except Exception:
                    # Don't interrupt persistence if WS fails
                    pass
            except Exception as e:
                logger.error(f"Django persistence hook error: {e}")

        self.persist_message_hook = _hook

    async def run(self, request: Optional[str] = None) -> str:
        """Execute the agent's main loop asynchronously.

        Args:
            request: Optional initial user request to process.

        Returns:
            A string summarizing the execution results.

        Raises:
            RuntimeError: If the agent is not in IDLE state at start.
        """
        if self.state != AgentState.IDLE:
            raise RuntimeError(f"Cannot run agent from state: {self.state}")

        if request:
            self.update_memory("user", request)

        results: List[str] = []
        async with self.state_context(AgentState.RUNNING):
            while (
                self.current_step < self.max_steps and self.state != AgentState.FINISHED
            ):
                self.current_step += 1
                logger.info(f"Executing step {self.current_step}/{self.max_steps}")
                if self.conversation_id:
                    await send_notification_async(
                        str(self.conversation_id),
                        "agent.step",
                        {"step": self.current_step, "max_steps": self.max_steps},
                    )
                step_result = await self.step()

                # Check for stuck state
                if self.is_stuck():
                    self.handle_stuck_state()

                results.append(f"Step {self.current_step}: {step_result}")

            if self.current_step >= self.max_steps:
                self.current_step = 0
                self.state = AgentState.IDLE
                results.append(f"Terminated: Reached max steps ({self.max_steps})")
        # Ensure all pending persistence operations complete before cleanup/return
        if self.pending_persist_tasks:
            pending = [t for t in self.pending_persist_tasks if not t.done()]
            if pending:
                try:
                    await asyncio.gather(*pending, return_exceptions=True)
                finally:
                    self.pending_persist_tasks.clear()
        await SANDBOX_CLIENT.cleanup()
        return "\n".join(results) if results else "No steps executed"

    @abstractmethod
    async def step(self) -> str:
        """Execute a single step in the agent's workflow.

        Must be implemented by subclasses to define specific behavior.
        """

    def handle_stuck_state(self):
        """Handle stuck state by adding a prompt to change strategy"""
        stuck_prompt = "\
        Observed duplicate responses. Consider new strategies and avoid repeating ineffective paths already attempted."
        self.next_step_prompt = f"{stuck_prompt}\n{self.next_step_prompt}"
        logger.warning(f"Agent detected stuck state. Added prompt: {stuck_prompt}")
        if self.conversation_id:
            # Beri tahu frontend bahwa agent terdeteksi macet dan strategi diubah
            import asyncio as _asyncio
            if _asyncio.get_event_loop().is_running():
                _ = _asyncio.create_task(
                    send_notification_async(
                        str(self.conversation_id),
                        "agent.stuck",
                        {"message": stuck_prompt},
                    )
                )

    def is_stuck(self) -> bool:
        """Check if the agent is stuck in a loop by detecting duplicate content"""
        if len(self.memory.messages) < 2:
            return False

        last_message = self.memory.messages[-1]
        if not last_message.content:
            return False

        # Count identical content occurrences
        duplicate_count = sum(
            1
            for msg in reversed(self.memory.messages[:-1])
            if msg.role == "assistant" and msg.content == last_message.content
        )

        return duplicate_count >= self.duplicate_threshold

    @property
    def messages(self) -> List[Message]:
        """Retrieve a list of messages from the agent's memory."""
        return self.memory.messages

    @messages.setter
    def messages(self, value: List[Message]):
        """Set the list of messages in the agent's memory."""
        self.memory.messages = value

