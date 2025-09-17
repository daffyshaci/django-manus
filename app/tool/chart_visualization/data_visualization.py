import asyncio
import json
import os
from typing import Any, Hashable

from pydantic import Field, model_validator

from app.config import config
from app.llm import LLM
from app.logger import logger
from app.tool.base import BaseTool
from app.sandbox.client import SANDBOX_CLIENT


class DataVisualization(BaseTool):
    name: str = "data_visualization"
    description: str = """Visualize statistical chart or Add insights in chart with JSON info from visualization_preparation tool. You can do steps as follows:
1. Visualize statistical chart
2. Choose insights into chart based on step 1 (Optional)
Outputs:
1. Charts (png/html)
2. Charts Insights (.md)(Optional)"""
    parameters: dict = {
        "type": "object",
        "properties": {
            "json_path": {
                "type": "string",
                "description": """file path of json info with ".json" in the end""",
            },
            "output_type": {
                "description": "Rendering format (html=interactive)",
                "type": "string",
                "default": "html",
                "enum": ["png", "html"],
            },
            "tool_type": {
                "description": "visualize chart or add insights",
                "type": "string",
                "default": "visualization",
                "enum": ["visualization", "insight"],
            },
            "language": {
                "description": "english(en) / chinese(zh)",
                "type": "string",
                "default": "en",
                "enum": ["zh", "en"],
            },
        },
        "required": ["code"],
    }
    llm: LLM = Field(default_factory=LLM, description="Language model instance")

    @model_validator(mode="after")
    def initialize_llm(self):
        """Initialize llm with default settings if not provided."""
        if self.llm is None or not isinstance(self.llm, LLM):
            self.llm = LLM(config_name=self.name.lower())
        return self

    def get_file_path(
        self,
        json_info: list[dict[str, str]],
        path_str: str,
        directory: str = None,
    ) -> list[str]:
        res = []
        for item in json_info:
            if os.path.exists(item[path_str]):
                res.append(item[path_str])
            elif os.path.exists(
                os.path.join(f"{directory or config.sandbox.work_dir}", item[path_str])
            ):
                res.append(
                    os.path.join(
                        f"{directory or config.sandbox.work_dir}", item[path_str]
                    )
                )
            else:
                raise Exception(f"No such file or directory: {item[path_str]}")
        return res

    def success_output_template(self, result: list[dict[str, str]]) -> str:
        content = ""
        if len(result) == 0:
            return "Is EMPTY!"
        for item in result:
            content += f"""## {item['title']}\nChart saved in: {item['chart_path']}"""
            if "insight_path" in item and item["insight_path"] and "insight_md" in item:
                content += "\n" + item["insight_md"]
            else:
                content += "\n"
        return f"Chart Generated Successful!\n{content}"

    async def data_visualization(
        self, json_info: list[dict[str, str]], output_type: str, language: str
    ) -> str:
        data_list = []
        # Build sandbox CSV paths and read via sandbox client (convert to JSON inside sandbox)
        csv_paths = []
        raw_paths = []
        for item in json_info:
            raw_path = item["csvFilePath"]
            raw_paths.append(raw_path)
            if raw_path.startswith("/"):
                spath = raw_path
            else:
                spath = os.path.join(config.sandbox.work_dir, raw_path)
            csv_paths.append(spath)
        # Ensure CSVs exist in sandbox; if missing, copy from host
        for i, spath in enumerate(csv_paths):
            try:
                # quick existence check by trying to read first bytes
                _ = await SANDBOX_CLIENT.run_command(f"test -f {spath} && head -c 1 {spath} >/dev/null && echo OK || echo NO")
                if "OK" not in (_ or ""):
                    parent = os.path.dirname(spath)
                    if parent:
                        await SANDBOX_CLIENT.run_command(f"mkdir -p {parent}")
                    await SANDBOX_CLIENT.copy_to(raw_paths[i], spath)
            except Exception:
                parent = os.path.dirname(spath)
                if parent:
                    await SANDBOX_CLIENT.run_command(f"mkdir -p {parent}")
                await SANDBOX_CLIENT.copy_to(raw_paths[i], spath)
        for index, item in enumerate(json_info):
            csv_path = csv_paths[index]
            # Convert CSV -> JSON inside sandbox using Python stdlib
            code = (
                "import csv, json\n"
                f"path = r'''{csv_path}'''\n"
                "with open(path, encoding='utf-8') as f:\n"
                "    reader = csv.DictReader(f)\n"
                "    data = list(reader)\n"
                "print(json.dumps(data, ensure_ascii=False))\n"
            )
            csv_json = await SANDBOX_CLIENT.code_run(code)

            data_list.append(
                {
                    "file_name": os.path.basename(csv_path).replace(
                        ".csv", ""
                    ),
                    "dict_data": csv_json,
                    "chartTitle": item["chartTitle"],
                }
            )
        tasks = [
            self.invoke_vmind(
                dict_data=item["dict_data"],
                chart_description=item["chartTitle"],
                file_name=item["file_name"],
                output_type=output_type,
                task_type="visualization",
                language=language,
            )
            for item in data_list
        ]

        results = await asyncio.gather(*tasks)
        error_list = []
        success_list = []
        for index, result in enumerate(results):
            csv_path = csv_paths[index]
            if "error" in result and "chart_path" not in result:
                error_list.append(f"Error in {csv_path}: {result['error']}")
            else:
                success_list.append(
                    {
                        **result,
                        "title": json_info[index]["chartTitle"],
                    }
                )
        if len(error_list) > 0:
            newline = '\n'
            return {
                "observation": f"# Error chart generated{newline.join(error_list)}\n{self.success_output_template(success_list)}",
                "success": False,
            }
        else:
            return {"observation": f"{self.success_output_template(success_list)}"}

    async def add_insighs(
        self, json_info: list[dict[str, str]], output_type: str
    ) -> str:
        data_list = []
        chart_paths = [item["chartPath"] for item in json_info]
        for index, item in enumerate(json_info):
            if "insights_id" in item:
                base = os.path.basename(chart_paths[index])
                file_name_no_ext = os.path.splitext(base)[0]
                data_list.append(
                    {
                        "file_name": file_name_no_ext,
                        "insights_id": item["insights_id"],
                    }
                )
        tasks = [
            self.invoke_vmind(
                insights_id=item["insights_id"],
                file_name=item["file_name"],
                output_type=output_type,
                task_type="insight",
            )
            for item in data_list
        ]
        results = await asyncio.gather(*tasks)
        error_list = []
        success_list = []
        for index, result in enumerate(results):
            chart_path = chart_paths[index]
            if "error" in result and "chart_path" not in result:
                error_list.append(f"Error in {chart_path}: {result['error']}")
            else:
                success_list.append(chart_path)
        success_template = (
            f"# Charts Update with Insights\n{','.join(success_list)}"
            if len(success_list) > 0
            else ""
        )
        if len(error_list) > 0:
            newline = '\n'
            return {
                "observation": f"# Error in chart insights:{newline.join(error_list)}\n{success_template}",
                "success": False,
            }
        else:
            return {"observation": f"{success_template}"}

    async def execute(
        self,
        json_path: str,
        output_type: str | None = "html",
        tool_type: str | None = "visualization",
        language: str | None = "en",
    ) -> str:
        try:
            logger.info(f"📈 data_visualization with {json_path} in: {tool_type} ")
            # Ensure sandbox is ready
            if not getattr(SANDBOX_CLIENT, "sandbox", None):
                await SANDBOX_CLIENT.create(config=config.sandbox)
            # Always read JSON info from sandbox path; if missing, copy from host into sandbox first
            spath = json_path if json_path.startswith("/") else os.path.join(config.sandbox.work_dir, json_path)
            try:
                json_str = await SANDBOX_CLIENT.read_file(spath)
            except Exception:
                # Attempt to copy from host to sandbox and re-read
                try:
                    await SANDBOX_CLIENT.copy_to(json_path, spath)
                    json_str = await SANDBOX_CLIENT.read_file(spath)
                except Exception as e:
                    return {
                        "observation": f"Error accessing JSON in sandbox: {e}",
                        "success": False,
                    }
            json_info = json.loads(json_str)
            if tool_type == "visualization":
                return await self.data_visualization(json_info, output_type, language)
            else:
                return await self.add_insighs(json_info, output_type)
        except Exception as e:
            return {
                "observation": f"Error: {e}",
                "success": False,
            }

    async def invoke_vmind(
        self,
        file_name: str,
        output_type: str,
        task_type: str,
        insights_id: list[str] = None,
        dict_data: list[dict[Hashable, Any]] = None,
        chart_description: str = None,
        language: str = "en",
    ):
        llm_config = {
            "base_url": self.llm.base_url,
            "model": self.llm.model,
            "api_key": self.llm.api_key,
        }
        vmind_params = {
            "llm_config": llm_config,
            "user_prompt": chart_description,
            "dataset": dict_data,
            "file_name": file_name,
            "output_type": output_type,
            "insights_id": insights_id,
            "task_type": task_type,
            "directory": str(config.sandbox.work_dir),
            "language": language,
        }
        # Prepare TS project inside sandbox and execute via sandbox client
        try:
            if not getattr(SANDBOX_CLIENT, "sandbox", None):
                await SANDBOX_CLIENT.create(config=config.sandbox)
            sandbox_dir = os.path.join(config.sandbox.work_dir, "chart_visualization")
            # Ensure folder structure exists
            await SANDBOX_CLIENT.run_command(f"mkdir -p {sandbox_dir}/src")
            # Write project files from local repo into sandbox (idempotent)
            local_dir = os.path.dirname(__file__)
            for fname in ["package.json", "tsconfig.json"]:
                local_path = os.path.join(local_dir, fname)
                try:
                    with open(local_path, "r", encoding="utf-8") as f:
                        await SANDBOX_CLIENT.write_file(os.path.join(sandbox_dir, fname), f.read())
                except Exception as e:
                    return {"error": f"Failed to stage {fname} into sandbox: {e}"}
            # src file
            ts_local = os.path.join(local_dir, "src", "chartVisualize.ts")
            try:
                with open(ts_local, "r", encoding="utf-8") as f:
                    await SANDBOX_CLIENT.write_file(os.path.join(sandbox_dir, "src", "chartVisualize.ts"), f.read())
            except Exception as e:
                return {"error": f"Failed to stage chartVisualize.ts into sandbox: {e}"}
            # Install deps if needed
            try:
                exists = await SANDBOX_CLIENT.run_command(
                    f"test -d {sandbox_dir}/node_modules && echo OK || echo NO"
                )
                if "OK" not in (exists or ""):
                    _ = await SANDBOX_CLIENT.run_command(
                        f"cd {sandbox_dir} && npm install --silent"
                    )
            except Exception:
                # Best-effort install
                _ = await SANDBOX_CLIENT.run_command(
                    f"cd {sandbox_dir} && npm install --silent"
                )
            # Provide input via file and stdin redirection to avoid quoting issues
            input_path = os.path.join(sandbox_dir, "input.json")
            await SANDBOX_CLIENT.write_file(input_path, json.dumps(vmind_params, ensure_ascii=False))
            cmd = (
                f"cd {sandbox_dir} && npx ts-node src/chartVisualize.ts < input.json "
                f"|| node --loader ts-node/esm src/chartVisualize.ts < input.json"
            )
            stdout = await SANDBOX_CLIENT.run_command(cmd, timeout=getattr(config.sandbox, "timeout", None))
            try:
                return json.loads(stdout)
            except Exception:
                return {"error": stdout}
        except Exception as e:
            return {"error": str(e)}
