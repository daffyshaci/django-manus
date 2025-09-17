from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import List, Optional, Callable
import asyncio
import time

from pydantic import BaseModel, Field, model_validator

from app.llm import LLM
from app.logger import logger
from app.sandbox.client import SANDBOX_CLIENT
from app.schema import ROLE_TYPE, AgentState, Memory, Message
from app.consumers.notifications import send_notification_async
from app.config import config, LLMSettings


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

    # LLM configuration overrides
    llm_overrides: Optional[dict] = Field(
        default=None,
        description="Optional LLM configuration overrides (model, temperature, etc.)",
    )

    # Optional persistence hook: (agent, role, content, base64_image, kwargs_dict) -> None | awaitable
    persist_message_hook: Optional[Callable[["BaseAgent", str, str, Optional[str], dict], None]] = Field(  # type: ignore
        default=None,
        description=(
            "Optional callable invoked after update_memory to persist message to external storage. "
            "Signature: (agent, role, content, base64_image, extra_kwargs)"
        ),
    )
    # New: Optional persistence hook for files/artifacts: (agent, items_list[dict]) -> None | awaitable
    persist_files_hook: Optional[Callable[["BaseAgent", List[dict]], None]] = Field(  # type: ignore
        default=None,
        description=(
            "Optional callable invoked by update_files to persist file artifacts to external storage. "
            "Each item dict may include: path, filename, size_bytes, sha256, mime_type, stored_content"
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
        # Always prioritize llm_overrides, even if a default LLM instance already exists
        if self.llm_overrides:
            # Generate unique config name based on conversation_id or agent name + timestamp
            unique_suffix = f"_{self.conversation_id}" if self.conversation_id else f"_{int(time.time())}"
            config_name = f"{self.name.lower()}{unique_suffix}"
            logger.info(
                f"Initializing LLM with overrides for conversation {self.conversation_id}, config_name: {config_name}"
            )
            logger.debug(f"LLM overrides: {self.llm_overrides}")
            # Merge overrides with base config and build a proper mapping for LLM
            try:
                base_map = config.llm  # Dict[str, LLMSettings]
                base_cfg = base_map.get(self.name.lower(), base_map["default"])  # type: ignore[index]
                base_data = (
                    base_cfg.model_dump() if hasattr(base_cfg, "model_dump") else base_cfg.dict()
                )
                merged_data = {**base_data, **(self.llm_overrides or {})}
                merged_cfg = LLMSettings(**merged_data)
                # Provide mapping with default and our unique config_name
                llm_map = {"default": base_cfg, config_name: merged_cfg}
                self.llm = LLM(config_name=config_name, llm_config=llm_map)  # type: ignore[arg-type]
                logger.info("LLM initialized successfully with overrides")
            except Exception as e:
                logger.exception(
                    f"Failed to apply llm_overrides, falling back to default config: {e}"
                )
                self.llm = LLM(config_name=self.name.lower())
        elif self.llm is None or not isinstance(self.llm, LLM):
            logger.info(f"Initializing LLM with default config: {self.name.lower()}")
            self.llm = LLM(config_name=self.name.lower())
            logger.info("LLM initialized successfully with default config")
        else:
            logger.debug(f"LLM already initialized: {type(self.llm)}")

        if not isinstance(self.memory, Memory):
            logger.debug("Initializing memory")
            self.memory = Memory()
            logger.debug("Memory initialized successfully")
        else:
            logger.debug("Memory already initialized")

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

    def update_files(self, files: List[dict] | dict, *, persist: bool = True) -> None:
        """Persist file artifacts related to current conversation.

        Each file item may contain:
        - path: absolute path in sandbox (e.g., /workspace/foo.txt)
        - filename: optional, derived from path if missing
        - size_bytes, sha256, mime_type: optional metadata
        - stored_content: optional snapshot of content (small text only)
        """
        items: List[dict] = files if isinstance(files, list) else [files]
        if not items:
            return
        if persist and self.persist_files_hook:
            try:
                result = self.persist_files_hook(self, items)
                if hasattr(result, "__await__"):
                    try:
                        loop = asyncio.get_running_loop()
                        task = loop.create_task(result)  # type: ignore[arg-type]
                        self.pending_persist_tasks.append(task)
                    except RuntimeError:
                        asyncio.run(result)  # type: ignore[arg-type]
            except Exception as e:
                logger.error(f"Error in persist_files_hook: {e}")

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

        async def _files_hook(agent: "BaseAgent", items: List[dict]):
            try:
                from asgiref.sync import sync_to_async
                from app.models import Conversation as ConversationDB
                from app.models import FileArtifact
                from django.utils import timezone as _tz
                import hashlib

                conv = await sync_to_async(ConversationDB.objects.get)(id=agent.conversation_id)
                for it in items:
                    path = (it.get("path") or "").strip()
                    if not path:
                        continue
                    
                    filename = (it.get("filename") or path.split("/")[-1]).strip()
                    
                    # Read file content from sandbox if not provided
                    stored_content = it.get("stored_content") or ""
                    size_bytes = it.get("size_bytes") or 0
                    sha256 = it.get("sha256") or ""
                    
                    # If content not provided, read from sandbox
                    if not stored_content and not size_bytes:
                        try:
                            # Read file content from sandbox
                            file_content = await SANDBOX_CLIENT.read_file(path)
                            stored_content = file_content
                            size_bytes = len(file_content.encode('utf-8'))
                            
                            # Calculate SHA256 hash
                            sha256_hash = hashlib.sha256()
                            sha256_hash.update(file_content.encode('utf-8'))
                            sha256 = sha256_hash.hexdigest()
                        except Exception as read_error:
                            logger.warning(f"Failed to read file {path} from sandbox: {read_error}")
                            # Continue with metadata only if file doesn't exist or can't be read
                            stored_content = ""
                            size_bytes = 0
                            sha256 = ""
                    
                    defaults = {
                        "filename": filename,
                        "size_bytes": size_bytes,
                        "sha256": sha256,
                        "mime_type": it.get("mime_type") or "",
                        "stored_content": stored_content,
                        "updated_at": _tz.now(),
                    }
                    # Update if exists for same conversation+path, else create
                    from django.db import transaction as _tx
                    async with _tx.async_atomic():
                        obj, created = await sync_to_async(FileArtifact.objects.update_or_create)(
                            conversation=conv,
                            path=path,
                            defaults=defaults,
                        )
                        # Emit WS event
                        try:
                            payload = {
                                "id": str(obj.id),
                                "conversation_id": str(conv.id),
                                "path": obj.path,
                                "filename": obj.filename,
                                "size_bytes": obj.size_bytes,
                                "sha256": obj.sha256,
                                "mime_type": obj.mime_type,
                                "created": created,
                                "created_at": obj.created_at.isoformat() if obj.created_at else None,
                                "updated_at": obj.updated_at.isoformat() if obj.updated_at else None,
                            }
                            await send_notification_async(str(conv.id), "file.created" if created else "file.updated", {"file": payload})
                        except Exception:
                            pass
            except Exception as e:
                logger.error(f"Django files persistence hook error: {e}")

        self.persist_files_hook = _files_hook

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
        
        # Clean up tool messages to reduce context size
        await self._cleanup_tool_messages()
        
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

    async def _cleanup_tool_messages(self) -> None:
        """Clean up tool messages to reduce context size for subsequent runs.
        
        This method compresses or removes content from tool messages that tend to be
        very large (like read, web_search results) while preserving metadata.
        """
        if not self.memory.messages or not self.conversation_id:
            logger.debug("No messages or conversation_id, skipping tool message cleanup")
            return
        
        try:
            from asgiref.sync import sync_to_async
            from app.models import Conversation as ConversationDB
            from django.utils import timezone as _tz
            
            # Get the conversation from database
            conv = await sync_to_async(ConversationDB.objects.get)(id=self.conversation_id)
            
            # Find tool messages that need cleanup
            tool_messages_to_clean = []
            for msg in self.memory.messages:
                if (msg.role == "tool" and 
                    hasattr(msg, 'name') and 
                    msg.name and 
                    msg.name.lower() in ['read', 'web_search'] and
                    hasattr(msg, 'content') and 
                    len(msg.content or '') > 1000):  # Only clean large messages
                    tool_messages_to_clean.append(msg)
            
            if not tool_messages_to_clean:
                logger.debug("No large tool messages found for cleanup")
                return
            
            logger.info(f"Cleaning up {len(tool_messages_to_clean)} tool messages for conversation {self.conversation_id}")
            
            # Clean each tool message
            for msg in tool_messages_to_clean:
                original_length = len(msg.content or '')
                
                if msg.name.lower() == 'read':
                    # For read operations, keep first few lines and summary
                    lines = msg.content.split('\n')
                    if len(lines) > 10:
                        msg.content = '\n'.join(lines[:5]) + '\n...\n[Content truncated for brevity]'
                        logger.debug(f"Truncated read message from {len(lines)} lines to 5 lines")
                elif msg.name.lower() == 'web_search':
                    # For web search, keep only metadata and first result
                    if 'Search results:' in msg.content:
                        # Extract just the first result summary
                        lines = msg.content.split('\n')
                        truncated_content = []
                        result_count = 0
                        for line in lines:
                            if line.startswith('- '):
                                result_count += 1
                                if result_count <= 2:  # Keep first 2 results
                                    truncated_content.append(line)
                            elif not line.startswith('Search results:'):
                                truncated_content.append(line)
                        if result_count > 2:
                            truncated_content.append(f'... and {result_count - 2} more results')
                        msg.content = '\n'.join(truncated_content)
                        logger.debug(f"Truncated web_search message from {result_count} results to 2 results")
                
                new_length = len(msg.content or '')
                logger.info(f"Cleaned {msg.name} message: {original_length} -> {new_length} chars (reduction: {original_length - new_length} chars)")
                
                # Update the message in database via persistence hook
                if self.persist_message_hook:
                    try:
                        await self.persist_message_hook(
                            self, 
                            "tool", 
                            msg.content, 
                            None, 
                            {"name": msg.name, "tool_call_id": getattr(msg, 'tool_call_id', None)}
                        )
                        logger.debug(f"Successfully persisted cleaned {msg.name} message")
                    except Exception as e:
                        logger.error(f"Failed to persist cleaned tool message: {e}")
                        
        except Exception as e:
            logger.error(f"Error in tool message cleanup: {e}")
            logger.exception("Detailed error in tool message cleanup:")

