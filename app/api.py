from ninja import Router
# from ninja.files import UploadedFile  # removed unused import
from ninja.security import django_auth

from .models import Conversation, Message, FileArtifact
from ninja import Schema, ModelSchema
from typing import List, Optional, Protocol,Any, TYPE_CHECKING
from uuid import UUID
from django.http import JsonResponse
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError
from common.auth import CombinedAuth
from .logger import logger
import os
from app.config import config

if TYPE_CHECKING:
    from users.models import User
else:
    User = get_user_model()

router = Router(tags=["chat"])

class ConversationSchema(ModelSchema):
    class Meta:
        model = Conversation
        fields = ['id', 'title', 'llm_model']


class ConversationCreateSchema(Schema):
    model: str
    content: str
    agent_type: Optional[str] = None
    llm_overrides: Optional[dict] = None
    # attachments: Optional[List[UUID]] = None  # List of attachment IDs


class MessageSchema(Schema):
    id: UUID
    conversation_id: UUID
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[dict]] = None
    tool_call_id: Optional[str] = None
    base64_image: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class MessageCreateSchema(Schema):
    content: str
    base64_image: Optional[str] = None
    attachments: Optional[List[UUID]] = None  # List of attachment IDs
    metadata: Optional[dict] = None  # accepted but not persisted currently


class FileArtifactSchema(ModelSchema):
    class Meta:
        model = FileArtifact
        fields = ['id', 'path', 'filename', 'size_bytes', 'sha256', 'mime_type', 'stored_content', 'created_at', 'updated_at']


class ConversationDetailSchema(Schema):
    conversation: ConversationSchema
    messages: List[MessageSchema]
    message_count: int
    total_cost: float
    first_initiate: bool  # New field to indicate if this is the first user message

class AuthenticatedRequest(Protocol):
    auth: "User"

@router.get(
    "/conversations", response=list[ConversationSchema], auth=CombinedAuth()
)
async def get_conversations(request) -> list[Conversation] | JsonResponse:
    try:
        logger.info(f"Retrieving conversations for user {request.auth.id}")
        queryset = [
            conv
            async for conv in Conversation.objects.filter(user=request.auth)
        ]
        logger.info(f"Retrieved {len(queryset)} conversations for user {request.auth.id}")
        return queryset
    except Exception as e:
        logger.error(f"Failed to retrieve conversations for user {request.auth.id}: {e}")
        logger.exception("Detailed error in get_conversations:")
        return JsonResponse({"error": "Failed to retrieve conversations", "detail": str(e)}, status=500)


@router.post(
    "/conversations", response=ConversationSchema, auth=CombinedAuth()
)
async def create_conversation(request: AuthenticatedRequest, data: ConversationCreateSchema) -> Conversation | JsonResponse:
    """
    Create a new conversation with an initial message and optional file attachments.
    """
    try:
        logger.info(f"Creating conversation for user {request.auth.id}, agent_type: {data.agent_type}")
        logger.debug(f"LLM overrides: {data.llm_overrides}")
        
        # Merge overrides with selected model so agent respects conversation model when overrides are empty
        overrides = dict(data.llm_overrides or {})
        if data.model and "model" not in overrides:
            overrides["model"] = data.model
        
        # create conversation
        conversation = await Conversation.objects.acreate(
            user=request.auth,
            title=data.content[:50],
            llm_model=data.model,  # map API field to model field
            agent_type=data.agent_type,
            llm_overrides=overrides
        )

        # create the initial message
        await Message.objects.acreate(
            conversation=conversation,
            role=Message.ROLE.USER,
            content=data.content,
        )

        # No I/O-bound operations here. Daytona volume provisioning is handled in Celery task.

        # Start background processing immediately after creating the conversation
        # Prepare overrides ensuring conversation's llm_model is respected
        task_overrides = dict(overrides or {})
        if conversation.llm_model and "model" not in task_overrides:
            task_overrides["model"] = conversation.llm_model
        from .tasks import run_manus_agent
        run_manus_agent.delay(
            data.content,
            str(conversation.id),
            agent_type=conversation.agent_type,
            llm_overrides=task_overrides
        )

        logger.info(f"Conversation created successfully: {conversation.id}")
        return conversation
    except IntegrityError as e:
        logger.error(f"Database integrity error creating conversation: {e}")
        return JsonResponse({"error": "Database integrity error", "detail": str(e)}, status=400)
    except ValidationError as e:
        logger.error(f"Validation error creating conversation: {e}")
        return JsonResponse({"error": "Validation error", "detail": str(e)}, status=400)
    except Exception as e:
        logger.error(f"Failed to create conversation for user {request.auth.id}: {e}")
        logger.exception("Detailed error in create_conversation:")
        return JsonResponse({"error": "Failed to create conversation", "detail": str(e)}, status=500)


@router.get(
    "/conversations/{conversation_id}",
    response=ConversationDetailSchema,
    auth=CombinedAuth()
)
async def get_conversation_detail(request: AuthenticatedRequest, conversation_id: UUID) -> dict[str, Any] | JsonResponse:
    """
    Get conversation details with all messages and artifacts.
    This endpoint is used when user enters the chat detail page.
    """
    try:
        # Verify conversation exists and belongs to user
        conversation = await Conversation.objects.aget(
            id=conversation_id, user=request.auth
        )

        # Get all messages for this conversation
        message_objects = []
        async for msg in Message.objects.filter(conversation=conversation).select_related('conversation').order_by('created_at'):
            message_objects.append(msg)

        # Convert messages to schema format with attachments
        messages: list[dict[str, Any]] = []
        for msg in message_objects:
            messages.append({
                "id": msg.id,
                "conversation_id": msg.conversation.id,
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat(),
                "updated_at": msg.updated_at.isoformat(),
                "tool_calls": msg.tool_calls,
                "tool_call_id": msg.tool_call_id,
                "base64_image": msg.base64_image
            })

        # Determine if this is a first initiate (only one user message)
        first_initiate = False
        if len(message_objects) == 1 and message_objects[0].role == Message.ROLE.USER:
            first_initiate = True

        return {
            "conversation": conversation,
            "messages": messages,
            "message_count": len(message_objects),
            "total_cost": 0.0,
            "first_initiate": first_initiate
        }
    except ObjectDoesNotExist:
        return JsonResponse({"error": "Conversation not found"}, status=404)
    except Exception as e:
        return JsonResponse({"error": "Failed to retrieve conversation details", "detail": str(e)}, status=500)


@router.post(
    "/conversations/{conversation_id}/messages",
    response=dict,
    auth=CombinedAuth()
)
async def send_message(request: AuthenticatedRequest, conversation_id: UUID, data: MessageCreateSchema) -> dict[str, Any] | JsonResponse:
    """
    Send a message to a conversation with optional file attachments.
    """
    try:
        # Verify conversation exists and belongs to user
        conversation = await Conversation.objects.aget(
            id=conversation_id, user=request.auth
        )

        # Create the message
        message = await Message.objects.acreate(
            conversation=conversation,
            role=Message.ROLE.USER,
            content=data.content,
            base64_image=data.base64_image,
        )

        # Prepare llm_overrides ensuring conversation's llm_model is respected
        overrides = dict(conversation.llm_overrides or {})
        if conversation.llm_model and "model" not in overrides:
            overrides["model"] = conversation.llm_model

        # process celery task here
        from .tasks import run_manus_agent
        run_manus_agent.delay(
            data.content, 
            str(conversation_id),
            agent_type=conversation.agent_type,
            llm_overrides=overrides
        )
        return {
            "message": "Message sent successfully",
            "message_id": str(message.id),
            "attachments_count": len(data.attachments or [])
        }
    except ObjectDoesNotExist:
        return JsonResponse({"error": "Conversation not found"}, status=404)
    except ValidationError as e:
        return JsonResponse({"error": "Message validation error", "detail": str(e)}, status=400)
    except IntegrityError as e:
        return JsonResponse({"error": "Database integrity error", "detail": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"error": "Failed to send message", "detail": str(e)}, status=500)


@router.post(
    "/conversations/{conversation_id}/trigger-first-message",
    response=dict,
    auth=CombinedAuth()
)
async def trigger_first_message(request: AuthenticatedRequest, conversation_id: UUID) -> dict[str, Any] | JsonResponse:
    """
    Trigger the first message processing for a conversation.
    This endpoint is called when first_initiate is True in the frontend.
    It will start a Celery task to process the conversation.
    """
    try:
        # Verify conversation exists and belongs to user
        conversation = await Conversation.objects.aget(
            id=conversation_id, user=request.auth
        )

        # get earliest user message content as prompt
        prompt = None
        async for msg in Message.objects.filter(conversation=conversation, role=Message.ROLE.USER).order_by("created_at"):
            prompt = msg.content
            break

        # Prepare llm_overrides ensuring conversation's llm_model is respected
        overrides = dict(conversation.llm_overrides or {})
        if conversation.llm_model and "model" not in overrides:
            overrides["model"] = conversation.llm_model

        from .tasks import run_manus_agent
        run_manus_agent.delay(
            prompt or "", 
            str(conversation_id),
            agent_type=conversation.agent_type,
            llm_overrides=overrides
        )

        return {
            "message": "First message processing triggered",
            "conversation_id": str(conversation.id)
        }

    except ObjectDoesNotExist:
        return JsonResponse({"error": "Conversation not found"}, status=404)
    except Exception as e:
        return JsonResponse({"error": "Failed to trigger first message processing", "detail": str(e)}, status=500)


@router.get(
    "/conversations/{conversation_id}/messages",
    response=list[MessageSchema],
    auth=CombinedAuth()
)
async def get_conversation_messages(request: AuthenticatedRequest, conversation_id: UUID) -> list[Message] | JsonResponse:
    """
    Get all messages for a conversation.
    This endpoint returns messages produced/used during the conversation.
    """
    try:
        # Verify conversation exists and belongs to user
        conversation = await Conversation.objects.aget(
            id=conversation_id, user=request.auth
        )
        logger.info(f"Retrieving messages for conversation {conversation_id}")

        # Get all messages for this conversation
        messages = []
        async for msg in Message.objects.filter(conversation=conversation).order_by('-created_at'):
            messages.append(msg)

        logger.info(f"Retrieved {len(messages)} messages for conversation {conversation_id}")
        if messages:
            logger.debug(f"Message details: {[{'id': str(m.id), 'conversation_id': m.conversation.id, 'content': m.content} for m in messages]}")
        
        return messages
    except ObjectDoesNotExist:
        logger.warning(f"Conversation not found: {conversation_id}")
        return JsonResponse({"error": "Conversation not found"}, status=404)
    except Exception as e:
        logger.error(f"Failed to retrieve conversation messages for {conversation_id}: {e}")
        logger.exception("Detailed error in get_conversation_messages:")
        return JsonResponse({"error": "Failed to retrieve conversation messages", "detail": str(e)}, status=500)


@router.get(
    "/conversations/{conversation_id}/files",
    response=list[FileArtifactSchema],
    auth=CombinedAuth()
)
async def get_conversation_files(request: AuthenticatedRequest, conversation_id: UUID) -> list[FileArtifact] | JsonResponse:
    """
    Get all file artifacts for a conversation.
    This endpoint returns files produced/used during the conversation.
    """
    try:
        # Verify conversation exists and belongs to user
        conversation = await Conversation.objects.aget(
            id=conversation_id, user=request.auth
        )
        logger.info(f"Retrieving files for conversation {conversation_id}")

        # Get all file artifacts for this conversation
        files = []
        async for file_artifact in FileArtifact.objects.filter(conversation=conversation).order_by('-created_at'):
            files.append(file_artifact)

        logger.info(f"Retrieved {len(files)} files for conversation {conversation_id}")
        if files:
            logger.debug(f"File details: {[{'id': str(f.id), 'path': f.path, 'size': f.size_bytes} for f in files]}")
        
        return files
    except ObjectDoesNotExist:
        logger.warning(f"Conversation not found: {conversation_id}")
        return JsonResponse({"error": "Conversation not found"}, status=404)
    except Exception as e:
        logger.error(f"Failed to retrieve conversation files for {conversation_id}: {e}")
        logger.exception("Detailed error in get_conversation_files:")
        return JsonResponse({"error": "Failed to retrieve conversation files", "detail": str(e)}, status=500)


@router.get(
    "/conversations/{conversation_id}/volume-info",
    response=dict,
    auth=CombinedAuth()
)
async def get_conversation_volume_info(request: AuthenticatedRequest, conversation_id: UUID) -> dict | JsonResponse:
    """Debug-only endpoint: returns Daytona volume info and configured work_dir for the conversation.
    This helps verify provisioning and mounting without exposing sensitive data beyond the authenticated user scope.
    """
    try:
        conv = await Conversation.objects.aget(id=conversation_id, user=request.auth)
        # Pull work_dir from settings/config
        from app.config import config as _cfg
        work_dir = None
        try:
            sbox = getattr(_cfg, 'sandbox', None)
            work_dir = getattr(sbox, 'work_dir', None)
        except Exception:
            work_dir = None
        return {
            "conversation_id": str(conv.id),
            "daytona_volume_id": conv.daytona_volume_id,
            "daytona_volume_name": conv.daytona_volume_name,
            "work_dir": work_dir,
        }
    except ObjectDoesNotExist:
        return JsonResponse({"error": "Conversation not found"}, status=404)
    except Exception as e:
        return JsonResponse({"error": "Failed to fetch volume info", "detail": str(e)}, status=500)
