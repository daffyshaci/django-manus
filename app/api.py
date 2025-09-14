from ninja import Router
# from ninja.files import UploadedFile  # removed unused import
from ninja.security import django_auth

from .models import Conversation, Message
from ninja import Schema, ModelSchema
from typing import List, Optional, Protocol,Any, TYPE_CHECKING
from uuid import UUID
from django.http import JsonResponse
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError
from common.auth import AsyncSessionAuth

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
    attachments: Optional[List[UUID]] = None  # List of attachment IDs
    metadata: Optional[dict] = None  # accepted but not persisted currently


class ConversationDetailSchema(Schema):
    conversation: ConversationSchema
    messages: List[MessageSchema]
    message_count: int
    total_cost: float
    first_initiate: bool  # New field to indicate if this is the first user message

class AuthenticatedRequest(Protocol):
    auth: "User"

@router.get(
    "/conversations", response=list[ConversationSchema], auth=AsyncSessionAuth()
)
async def get_conversations(request) -> list[Conversation] | JsonResponse:
    try:
        queryset = [
            conv
            async for conv in Conversation.objects.filter(user=request.auth)
        ]
        return queryset
    except Exception as e:
        return JsonResponse({"error": "Failed to retrieve conversations", "detail": str(e)}, status=500)


@router.post(
    "/conversations", response=ConversationSchema, auth=AsyncSessionAuth()
)
async def create_conversation(request: AuthenticatedRequest, data: ConversationCreateSchema) -> Conversation | JsonResponse:
    """
    Create a new conversation with an initial message and optional file attachments.
    """
    try:
        # create conversation
        conversation = await Conversation.objects.acreate(
            user=request.auth,
            llm_model=data.model,  # map API field to model field
        )

        # create the initial message
        await Message.objects.acreate(
            conversation=conversation,
            role=Message.ROLE.USER,
            content=data.content,
        )

        return conversation
    except IntegrityError as e:
        return JsonResponse({"error": "Database integrity error", "detail": str(e)}, status=400)
    except ValidationError as e:
        return JsonResponse({"error": "Validation error", "detail": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"error": "Failed to create conversation", "detail": str(e)}, status=500)


@router.get(
    "/conversations/{conversation_id}",
    response=ConversationDetailSchema,
    auth=AsyncSessionAuth()
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
    auth=AsyncSessionAuth()
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
        )

        # process celery task here
        from .tasks import run_manus_agent
        run_manus_agent.delay(data.content, str(conversation_id))
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
    auth=AsyncSessionAuth()
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

        from .tasks import run_manus_agent
        run_manus_agent.delay(prompt or "", str(conversation_id))

        return {
            "message": "First message processing triggered",
            "conversation_id": str(conversation.id)
        }

    except ObjectDoesNotExist:
        return JsonResponse({"error": "Conversation not found"}, status=404)
    except Exception as e:
        return JsonResponse({"error": "Failed to trigger first message processing", "detail": str(e)}, status=500)
