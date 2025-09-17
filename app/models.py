from django.db import models
from common.models import TimeStampedUUIDModel
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from typing import Any, List, Literal, Optional, Union
from django.utils import timezone

User = get_user_model()

class Conversation(TimeStampedUUIDModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations')
    title = models.CharField(max_length=255, blank=True, null=True)
    llm_model = models.CharField(max_length=255, blank=True, null=True)
    agent_type = models.CharField(max_length=255, blank=True, null=True)
    llm_overrides = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.title or ''}"

class Message(TimeStampedUUIDModel):
    class ROLE(models.TextChoices):
        SYSTEM = 'system', _('System')
        USER = 'user', _('User')
        ASSISTANT = 'assistant', _('Assistant')
        TOOL = 'tool', _('Tool')

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    name = models.CharField(max_length=255, blank=True, null=True)
    content = models.TextField(blank=True, null=True)
    role = models.CharField(max_length=255, choices=ROLE.choices, default=ROLE.USER)
    tool_calls = models.JSONField(default=list, blank=True)
    tool_call_id = models.CharField(max_length=255, blank=True, null=True)
    base64_image = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.role} - {(self.content[:200] if self.content else '')}"

    def to_dict(self) -> dict:
        """Convert message to dictionary format"""
        message = {"role": self.role}
        if self.content is not None:
            message["content"] = self.content
        if self.tool_calls is not None:
            # tool_calls stored as JSON (list of dicts) in DB; use as-is
            message["tool_calls"] = self.tool_calls
        if self.name is not None:
            message["name"] = self.name
        if self.tool_call_id is not None:
            message["tool_call_id"] = self.tool_call_id
        if self.base64_image is not None:
            message["base64_image"] = self.base64_image
        return message

    @classmethod
    def user_message(
        cls, conversation: "Conversation", content: str, base64_image: Optional[str] = None
    ) -> "Message":
        """Create and persist a user message"""
        obj = cls(conversation=conversation, role=cls.ROLE.USER, content=content, base64_image=base64_image)
        obj.save()
        return obj

    @classmethod
    def system_message(cls, conversation: "Conversation", content: str) -> "Message":
        """Create and persist a system message"""
        obj = cls(conversation=conversation, role=cls.ROLE.SYSTEM, content=content)
        obj.save()
        return obj

    @classmethod
    def assistant_message(
        cls, conversation: "Conversation", content: Optional[str] = None, base64_image: Optional[str] = None
    ) -> "Message":
        """Create and persist an assistant message"""
        obj = cls(conversation=conversation, role=cls.ROLE.ASSISTANT, content=content, base64_image=base64_image)
        obj.save()
        return obj

    @classmethod
    def tool_message(
        cls, conversation: "Conversation", content: str, name, tool_call_id: str, base64_image: Optional[str] = None
    ) -> "Message":
        """Create and persist a tool message"""
        obj = cls(
            conversation=conversation,
            role=cls.ROLE.TOOL,
            content=content,
            name=name,
            tool_call_id=tool_call_id,
            base64_image=base64_image,
        )
        obj.save()
        return obj

    @classmethod
    def from_tool_calls(
        cls,
        conversation: "Conversation",
        tool_calls: List[Any],
        content: Union[str, List[str]] = "",
        base64_image: Optional[str] = None,
        **kwargs,
    ) -> "Message":
        """Create and persist assistant message from raw tool calls.

        Args:
            conversation: Conversation to attach the message to
            tool_calls: Raw tool calls from LLM (list of pydantic objects or dicts)
            content: Optional message content
            base64_image: Optional base64 encoded image
        """
        formatted_calls: List[dict] = []
        for call in tool_calls:
            if isinstance(call, dict):
                # Assume dict already contains id, function (dict), and type
                formatted_calls.append(call)
            else:
                # Likely a pydantic model with id and function having model_dump()/dict()
                func = getattr(call.function, "model_dump", None) or getattr(call.function, "dict", None)
                func_payload = func() if callable(func) else getattr(call.function, "__dict__", {})
                formatted_calls.append({
                    "id": getattr(call, "id", None),
                    "function": func_payload,
                    "type": "function",
                })
        obj = cls(
            conversation=conversation,
            role=cls.ROLE.ASSISTANT,
            content=content,
            tool_calls=formatted_calls,
            base64_image=base64_image,
            **kwargs,
        )
        obj.save()
        return obj

class Memory(TimeStampedUUIDModel):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='memories')
    messages = models.JSONField(default=list, blank=True)
    max_messages = models.IntegerField(default=100)

    def add_message(self, message: Union[Message, dict]) -> None:
        """Add a message to memory (stored as JSON dict) and persist changes"""
        if isinstance(message, Message):
            payload = message.to_dict()
        elif isinstance(message, dict):
            payload = message
        else:
            # Fallback: try best-effort serialization
            payload = {
                "role": getattr(message, "role", None),
                "content": getattr(message, "content", None),
            }
        self.messages.append(payload)
        # Implement message limit
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages :]
        self.save(update_fields=["messages"])

    def add_messages(self, messages: List[Union[Message, dict]]) -> None:
        """Add multiple messages to memory (stored as JSON dict) and persist changes"""
        for m in messages:
            self.add_message(m)

    def clear(self) -> None:
        """Clear all messages and persist changes"""
        self.messages = []
        self.save(update_fields=["messages"])

    def get_recent_messages(self, n: int) -> List[dict]:
        """Get n most recent messages as dicts"""
        return self.messages[-n:]

    def to_dict_list(self) -> List[dict]:
        """Convert messages to list of dicts"""
        # Messages are stored as dicts; if any legacy entries exist, coerce them
        result: List[dict] = []
        for item in self.messages:
            if isinstance(item, dict):
                result.append(item)
            elif isinstance(item, Message):
                result.append(item.to_dict())
            else:
                result.append({
                    "role": getattr(item, "role", None),
                    "content": getattr(item, "content", None),
                })
        return result


class FileArtifact(models.Model):
    """Stores metadata about files produced/used in a conversation."""

    conversation = models.ForeignKey(
        'Conversation', on_delete=models.CASCADE, related_name='files'
    )
    path = models.CharField(max_length=512)
    filename = models.CharField(max_length=255)
    size_bytes = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, default="")
    mime_type = models.CharField(max_length=100, blank=True, default="")
    stored_content = models.TextField(blank=True, default="")  # optional snapshot of content
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["conversation", "filename"]),
            models.Index(fields=["conversation", "path"]),
        ]

    def __str__(self) -> str:
        return f"{self.filename} ({self.path})"

