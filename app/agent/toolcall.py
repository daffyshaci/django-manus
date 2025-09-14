import asyncio
import json
from typing import Any, List, Optional, Union

from pydantic import Field

from app.agent.react import ReActAgent
from app.exceptions import TokenLimitExceeded
from app.logger import logger
from app.prompt.toolcall import NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.schema import TOOL_CHOICE_TYPE, AgentState, Message, ToolCall, ToolChoice
from app.tool import CreateChatCompletion, Terminate, ToolCollection
from app.consumers.notifications import send_notification_async


TOOL_CALL_REQUIRED = "Tool calls required but none provided"


class ToolCallAgent(ReActAgent):
    """Base agent class for handling tool/function calls with enhanced abstraction"""

    name: str = "toolcall"
    description: str = "an agent that can execute tool calls."

    system_prompt: str = SYSTEM_PROMPT
    next_step_prompt: str = NEXT_STEP_PROMPT

    available_tools: ToolCollection = ToolCollection(
        CreateChatCompletion(), Terminate()
    )
    tool_choices: TOOL_CHOICE_TYPE = ToolChoice.AUTO  # type: ignore
    special_tool_names: List[str] = Field(default_factory=lambda: [Terminate().name])

    tool_calls: List[ToolCall] = Field(default_factory=list)
    _current_base64_image: Optional[str] = None

    max_steps: int = 30
    max_observe: Optional[Union[int, bool]] = None

    async def think(self) -> bool:
        """Process current state and decide next actions using tools"""
        if self.next_step_prompt:
            # Inject internal guidance for LLM only (do not persist)
            self.update_memory("user", self.next_step_prompt, persist=False)

        try:
            # Get response with tool options
            response = await self.llm.ask_tool(
                messages=self.messages,
                system_msgs=(
                    [Message.system_message(self.system_prompt)]
                    if self.system_prompt
                    else None
                ),
                tools=self.available_tools.to_params(),
                tool_choice=self.tool_choices,
            )
        except ValueError:
            raise
        except Exception as e:
            # Check if this is a RetryError containing TokenLimitExceeded
            if hasattr(e, "__cause__") and isinstance(e.__cause__, TokenLimitExceeded):
                token_limit_error = e.__cause__
                logger.error(
                    f"🚨 Token limit error (from RetryError): {token_limit_error}"
                )
                if self.conversation_id:
                    await send_notification_async(
                        str(self.conversation_id),
                        "agent.error",
                        {"type": "token_limit", "detail": str(token_limit_error)},
                    )
                self.update_memory(
                    "assistant",
                    f"Maximum token limit reached, cannot continue execution: {str(token_limit_error)}",
                )
                self.state = AgentState.FINISHED
                return False
            raise

        self.tool_calls = tool_calls = (
            response.tool_calls if response and response.tool_calls else []
        )
        content = response.content if response and response.content else ""

        # Log response info
        logger.info(f"✨ {self.name}'s thoughts: {content}")
        if self.conversation_id:
            await send_notification_async(
                str(self.conversation_id),
                "agent.thoughts",
                {"content": content},
            )
        logger.info(
            f"🛠️ {self.name} selected {len(tool_calls) if tool_calls else 0} tools to use"
        )
        if self.conversation_id:
            await send_notification_async(
                str(self.conversation_id),
                "agent.tools_selected",
                {"count": len(tool_calls) if tool_calls else 0},
            )
        if tool_calls:
            logger.info(
                f"🧰 Tools being prepared: {[call.function.name for call in tool_calls]}"
            )
            if self.conversation_id:
                await send_notification_async(
                    str(self.conversation_id),
                    "agent.tools_prepared",
                    {"tools": [call.function.name for call in tool_calls]},
                )
            logger.info(f"🔧 Tool arguments: {tool_calls[0].function.arguments}")
            if self.conversation_id:
                await send_notification_async(
                    str(self.conversation_id),
                    "agent.tool_args",
                    {"arguments": tool_calls[0].function.arguments},
                )

        try:
            if response is None:
                raise RuntimeError("No response received from the LLM")

            # Handle different tool_choices modes
            if self.tool_choices == ToolChoice.NONE:
                if tool_calls:
                    logger.warning(
                        f"🤔 Hmm, {self.name} tried to use tools when they weren't available!"
                    )
                if content:
                    self.update_memory("assistant", content)
                    return True
                return False

            # Add assistant message (with tool_calls when present)
            if self.tool_choices == ToolChoice.REQUIRED and not self.tool_calls:
                # Still record model's content even if tools are required and none provided
                if content:
                    self.update_memory("assistant", content)
                return True  # Will be handled in act()

            if self.tool_choices == ToolChoice.AUTO and not self.tool_calls:
                if content:
                    self.update_memory("assistant", content)
                # Continue only if there are tools selected
                return bool(content)

            # Default path: assistant decides to use tools
            # If any selected tool is a special tool (e.g., terminate), do NOT persist the assistant content or tool_calls
            if any(self._is_special_tool(call.function.name) for call in self.tool_calls):
                # Skip persisting assistant message to avoid awkward history entries for terminate
                return bool(self.tool_calls)
            # Otherwise, record assistant's content and tool calls in memory
            self.update_memory("assistant", content, tool_calls=self.tool_calls)
            return bool(self.tool_calls)
        except Exception as e:
            logger.error(f"🚨 Oops! The {self.name}'s thinking process hit a snag: {e}")
            if self.conversation_id:
                await send_notification_async(
                    str(self.conversation_id),
                    "agent.error",
                    {"type": "think_error", "detail": str(e)},
                )
            self.update_memory("assistant", f"Error encountered while processing: {str(e)}")
            return False

    async def act(self) -> str:
        """Execute tool calls and handle their results"""
        if not self.tool_calls:
            if self.tool_choices == ToolChoice.REQUIRED:
                raise ValueError(TOOL_CALL_REQUIRED)

            # Internal guidance to push model to terminate if final (do not persist)
            self.update_memory(
                role="user",
                content="The LLM does not call any tool. Consider whether the last response is the final answer. If it is, invoke the `terminate` tool.",
                persist=False,
            )
            if self.conversation_id:
                await send_notification_async(
                    str(self.conversation_id),
                    "agent.no_tool",
                    {"message": "LLM did not call any tool"},
                )
            return "Guidance added: Consider using terminate tool if this is final answer"

        results = []
        for command in self.tool_calls:
            # Reset base64_image for each tool call
            self._current_base64_image = None

            result = await self.execute_tool(command)

            if self.max_observe:
                result = result[: self.max_observe]

            logger.info(
                f"🎯 Tool '{command.function.name}' completed its mission! Result: {result}"
            )

            # Add tool response to memory via update_memory (persists through hook),
            # except for special tools like 'terminate' where we intentionally skip persistence
            if not self._is_special_tool(command.function.name):
                self.update_memory(
                    role="tool",
                    content=result,
                    tool_call_id=command.id,
                    name=command.function.name,
                    base64_image=self._current_base64_image,
                )
                results.append(result)
            else:
                # For terminate, we skip saving the tool message to keep history clean
                logger.info("Skipping persistence for special tool result: %s", command.function.name)

        return "\n\n".join(results)

    async def execute_tool(self, command: ToolCall) -> str:
        """Execute a single tool call with robust error handling"""
        if not command or not command.function or not command.function.name:
            return "Error: Invalid command format"

        name = command.function.name
        if name not in self.available_tools.tool_map:
            return f"Error: Unknown tool '{name}'"

        try:
            # Parse arguments
            args = json.loads(command.function.arguments or "{}")

            # Execute the tool
            logger.info(f"🔧 Activating tool: '{name}'...")
            result = await self.available_tools.execute(name=name, tool_input=args)

            # Handle special tools
            await self._handle_special_tool(name=name, result=result)

            # Check if result is a ToolResult with base64_image
            if hasattr(result, "base64_image") and result.base64_image:
                # Store the base64_image for later use in tool_message
                self._current_base64_image = result.base64_image

            # Format result for display (standard case)
            observation = (
                f"Observed output of cmd `{name}` executed:\n{str(result)}"
                if result
                else f"Cmd `{name}` completed with no output"
            )

            return observation
        except json.JSONDecodeError:
            error_msg = f"Error parsing arguments for {name}: Invalid JSON format"
            logger.error(
                f"📝 Oops! The arguments for '{name}' don't make sense - invalid JSON, arguments:{command.function.arguments}"
            )
            if self.conversation_id:
                await send_notification_async(
                    str(self.conversation_id),
                    "agent.tool_error",
                    {"tool": name, "error": error_msg},
                )
            return f"Error: {error_msg}"
        except Exception as e:
            error_msg = f"⚠️ Tool '{name}' encountered a problem: {str(e)}"
            logger.exception(error_msg)
            if self.conversation_id:
                await send_notification_async(
                    str(self.conversation_id),
                    "agent.tool_error",
                    {"tool": name, "error": str(e)},
                )
            return f"Error: {error_msg}"

    async def _handle_special_tool(self, name: str, result: Any, **kwargs):
        """Handle special tool execution and state changes"""
        if not self._is_special_tool(name):
            return

        if self._should_finish_execution(name=name, result=result, **kwargs):
            # Set agent state to finished
            logger.info(f"🏁 Special tool '{name}' has completed the task!")
            if self.conversation_id:
                await send_notification_async(
                    str(self.conversation_id),
                    "agent.finished",
                    {"tool": name},
                )
            self.state = AgentState.FINISHED

    @staticmethod
    def _should_finish_execution(**kwargs) -> bool:
        """Determine if tool execution should finish the agent"""
        return True

    def _is_special_tool(self, name: str) -> bool:
        """Check if tool name is in special tools list"""
        return name.lower() in [n.lower() for n in self.special_tool_names]

    async def cleanup(self):
        """Clean up resources used by the agent's tools."""
        logger.info(f"🧹 Cleaning up resources for agent '{self.name}'...")
        if self.conversation_id:
            await send_notification_async(
                str(self.conversation_id),
                "agent.cleanup_start",
                {"agent": self.name},
            )
        for tool_name, tool_instance in self.available_tools.tool_map.items():
            if hasattr(tool_instance, "cleanup") and asyncio.iscoroutinefunction(
                tool_instance.cleanup
            ):
                try:
                    logger.debug(f"🧼 Cleaning up tool: {tool_name}")
                    await tool_instance.cleanup()
                except Exception as e:
                    logger.error(
                        f"🚨 Error cleaning up tool '{tool_name}': {e}", exc_info=True
                    )
        logger.info(f"✨ Cleanup complete for agent '{self.name}'.")
        if self.conversation_id:
            await send_notification_async(
                str(self.conversation_id),
                "agent.cleanup_done",
                {"agent": self.name},
            )

    async def run(self, request: Optional[str] = None) -> str:
        """Run the agent with cleanup when done."""
        try:
            return await super().run(request)
        finally:
            await self.cleanup()
