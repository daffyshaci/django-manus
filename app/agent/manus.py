from typing import Dict, List

from pydantic import Field

# from app.agent.browser import BrowserContextHelper
from app.agent.toolcall import ToolCallAgent
from app.config import config
from app.logger import logger
from app.prompt.manus import NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.tool import Terminate, ToolCollection
from app.tool.ask_human import AskHuman
# from app.tool.browser_use_tool import BrowserUseTool
from app.tool.web_search import WebSearch
from app.tool.mcp import MCPClients, MCPClientTool
from app.tool.python_execute import PythonExecute
from app.tool.str_replace_editor import StrReplaceEditor
from app.consumers.notifications import send_notification_async


class Manus(ToolCallAgent):
    """A versatile general-purpose agent with support for both local and MCP tools."""

    name: str = "Manus"
    description: str = "A versatile agent that can solve various tasks using multiple tools including MCP-based tools"

    system_prompt: str = SYSTEM_PROMPT.format(directory=config.workspace_root)
    next_step_prompt: str = NEXT_STEP_PROMPT

    max_observe: int = 10000
    max_steps: int = 50

    # MCP clients for remote tool access
    mcp_clients: MCPClients = Field(default_factory=MCPClients)

    # Add general-purpose tools to the tool collection
    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(
            PythonExecute(),
            # BrowserUseTool(),
            WebSearch(),
            StrReplaceEditor(),
            AskHuman(),
            Terminate(),
        )
    )

    special_tool_names: list[str] = Field(default_factory=lambda: [Terminate().name])

    # Track connected MCP servers
    connected_servers: Dict[str, str] = Field(default_factory=dict)  # server_id -> url/command
    _initialized: bool = False

    @classmethod
    async def create(cls, **kwargs) -> "Manus":
        """Factory method to create and properly initialize a Manus instance."""
        instance = cls(**kwargs)
        # Attach Django persistence automatically if conversation_id provided
        conv_id = kwargs.get("conversation_id")
        if conv_id:
            try:
                instance.attach_django_persistence(str(conv_id))
                # Preload history from DB into in-memory memory so the agent has context
                try:
                    from app.models import Conversation as ConversationDB
                    from app.models import Memory as MemoryDB
                    from app.models import Message as MessageDB

                    # gunakan ORM async
                    conv = await ConversationDB.objects.aget(id=str(conv_id))
                    messages_payload = []
                    try:
                        memory_db = await MemoryDB.objects.aget(conversation=conv)
                        messages_payload = memory_db.to_dict_list()
                    except MemoryDB.DoesNotExist:
                        # fallback baca semua Message secara async
                        temp_msgs = []
                        async for m in MessageDB.objects.filter(conversation=conv).order_by("created_at"):
                            temp_msgs.append(m)
                        messages_payload = [m.to_dict() for m in temp_msgs]

                    if messages_payload:
                        from app.schema import Message as SchemaMessage
                        parsed_msgs = []
                        for payload in messages_payload:
                            try:
                                parsed_msgs.append(SchemaMessage(**payload))
                            except Exception as e:
                                logger.error(f"Skipping unparsable message from DB: {e}")
                        if parsed_msgs:
                            instance.memory.add_messages(parsed_msgs)
                            if instance.conversation_id:
                                await send_notification_async(
                                    str(instance.conversation_id),
                                    "agent.history_loaded",
                                    {"count": len(parsed_msgs)},
                                )
                except Exception as e:
                    logger.error(f"Failed to preload conversation history: {e}")
                    if instance.conversation_id:
                        await send_notification_async(
                            str(instance.conversation_id),
                            "agent.history_load_error",
                            {"error": str(e)},
                        )
            except Exception as e:
                logger.error(f"Failed to attach Django persistence: {e}")
                if instance.conversation_id:
                    await send_notification_async(
                        str(instance.conversation_id),
                        "agent.persistence_error",
                        {"error": str(e)},
                    )
        # await instance.initialize_mcp_servers()
        instance._initialized = True
        return instance

    async def cleanup(self):
        """Clean up Manus agent resources."""
        # Disconnect from all MCP servers only if we were initialized
        if self._initialized:
            # await self.disconnect_mcp_server()
            self._initialized = False

    async def think(self) -> bool:
        """Process current state and decide next actions with appropriate context."""
        if not self._initialized:
            # await self.initialize_mcp_servers()
            self._initialized = True

        result = await super().think()
        return result

    async def initialize_mcp_servers(self) -> None:
        """Initialize connections to configured MCP servers."""
        for server_id, server_config in config.mcp_config.servers.items():
            try:
                if server_config.type == "sse":
                    if server_config.url:
                        await self.connect_mcp_server(server_config.url, server_id)
                        logger.info(
                            f"Connected to MCP server {server_id} at {server_config.url}"
                        )
                        if self.conversation_id:
                            await send_notification_async(
                                str(self.conversation_id),
                                "agent.mcp_connected",
                                {"server_id": server_id, "type": "sse", "target": server_config.url},
                            )
                elif server_config.type == "stdio":
                    if server_config.command:
                        await self.connect_mcp_server(
                            server_config.command,
                            server_id,
                            use_stdio=True,
                            stdio_args=server_config.args,
                        )
                        logger.info(
                            f"Connected to MCP server {server_id} using command {server_config.command}"
                        )
                        if self.conversation_id:
                            await send_notification_async(
                                str(self.conversation_id),
                                "agent.mcp_connected",
                                {"server_id": server_id, "type": "stdio", "target": server_config.command},
                            )
            except Exception as e:
                logger.error(f"Failed to connect to MCP server {server_id}: {e}")
                if self.conversation_id:
                    await send_notification_async(
                        str(self.conversation_id),
                        "agent.mcp_connect_error",
                        {"server_id": server_id, "error": str(e)},
                    )

    async def connect_mcp_server(
        self,
        server_url: str,
        server_id: str = "",
        use_stdio: bool = False,
        stdio_args: List[str] = None,
    ) -> None:
        """Connect to an MCP server and add its tools."""
        if use_stdio:
            await self.mcp_clients.connect_stdio(
                server_url, stdio_args or [], server_id
            )
            self.connected_servers[server_id or server_url] = server_url
        else:
            await self.mcp_clients.connect_sse(server_url, server_id)
            self.connected_servers[server_id or server_url] = server_url

        # Update available tools with only the new tools from this server
        new_tools = [
            tool for tool in self.mcp_clients.tools if tool.server_id == server_id
        ]
        self.available_tools.add_tools(*new_tools)

    async def disconnect_mcp_server(self, server_id: str = "") -> None:
        """Disconnect from an MCP server and remove its tools."""
        await self.mcp_clients.disconnect(server_id)
        if server_id:
            self.connected_servers.pop(server_id, None)
        else:
            self.connected_servers.clear()

        # Rebuild available tools without the disconnected server's tools
        base_tools = [
            tool
            for tool in self.available_tools.tools
            if not isinstance(tool, MCPClientTool)
        ]
        self.available_tools = ToolCollection(*base_tools)
        self.available_tools.add_tools(*self.mcp_clients.tools)
