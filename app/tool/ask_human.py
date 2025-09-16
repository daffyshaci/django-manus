from typing import Any, Dict, List, Optional

from app.tool import BaseTool
from app.tool.base import ToolResult


class AskHuman(BaseTool):
    """Add a tool to ask human for help."""

    name: str = "ask_human"
    description: str = "Use this tool to ask the user a question with optional attachments and response options.."
    parameters: dict = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question you want to ask the user.",
            },
            "attachments": {
                "type": "array",
                "description": "Optional attachments to include with the question.",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "description": "The type of attachment (e.g., 'image', 'file').",
                        },
                        "url": {
                            "type": "string",
                            "description": "The URL of the attachment.",
                        },
                    },
                },
            },
            "response_options": {
                "type": "array",
                "description": "Optional response options for the user.",
                "items": {
                    "type": "string",
                },
            },
        },
        "required": ["question"],
    }

    async def execute(
        self,
        question: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
        response_options: Optional[List[str]] = None,
    ) -> ToolResult:
        """Return a structured payload to prompt the human via the Django UI.

        The agent will persist an assistant message and stop its loop, waiting for the next user reply.
        """
        payload: Dict[str, Any] = {
            "type": "ask_human",
            "question": question,
            "attachments": attachments or [],
            "response_options": response_options or [],
        }
        return ToolResult(output=payload, status="awaiting_user")
