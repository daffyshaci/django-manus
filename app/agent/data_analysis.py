from pydantic import Field

from app.agent.toolcall import ToolCallAgent
from app.config import config
from app.prompt.visualization import NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.tool import Terminate, ToolCollection
from app.tool.chart_visualization.chart_prepare import VisualizationPrepare
from app.tool.chart_visualization.data_visualization import DataVisualization
from app.tool.chart_visualization.python_execute import NormalPythonExecute


class DataAnalysis(ToolCallAgent):
    """
    A data analysis agent that uses planning to solve various data analysis tasks.

    This agent extends ToolCallAgent with a comprehensive set of tools and capabilities,
    including Data Analysis, Chart Visualization, Data Report.
    """

    name: str = "Data_Analysis"
    description: str = "An analytical agent that utilizes python and data visualization tools to solve diverse data analysis tasks"

    system_prompt: str = SYSTEM_PROMPT.format(directory=config.sandbox.work_dir)
    next_step_prompt: str = NEXT_STEP_PROMPT

    max_observe: int = 15000
    max_steps: int = 20

    # Add general-purpose tools to the tool collection
    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(
            NormalPythonExecute(),
            VisualizationPrepare(),
            DataVisualization(),
            Terminate(),
        )
    )

    @classmethod
    async def create(cls, **kwargs) -> "DataAnalysis":
        """Factory method to create and properly initialize a DataAnalysis instance."""
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
                    # Selalu baca dari tabel Message sebagai single source of truth
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
                                from app.logger import logger
                                logger.error(f"Skipping unparsable message from DB: {e}")
                        if parsed_msgs:
                            instance.memory.add_messages(parsed_msgs)
                except Exception as e:
                    from app.logger import logger
                    logger.error(f"Failed to preload conversation history: {e}")
            except Exception as e:
                from app.logger import logger
                logger.error(f"Failed to attach Django persistence: {e}")
        return instance
