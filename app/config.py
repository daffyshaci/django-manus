import json
import threading
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


def get_project_root() -> Path:
    """Get the project root directory"""
    return Path(__file__).resolve().parent.parent

PROJECT_ROOT = get_project_root()

WORKSPACE_ROOT = "/home/daytona/workspace"


class LLMSettings(BaseModel):
    model: str = Field(..., description="Model name")
    base_url: str = Field(..., description="API base URL")
    api_key: str = Field(..., description="API key")
    max_tokens: int = Field(4096, description="Maximum number of tokens per request")
    max_input_tokens: Optional[int] = Field(
        None,
        description="Maximum input tokens to use across all requests (None for unlimited)",
    )
    temperature: float = Field(1.0, description="Sampling temperature")
    api_type: str = Field(..., description="Azure, Openai, or Ollama")
    api_version: str = Field(..., description="Azure Openai version if AzureOpenai")


class ProxySettings(BaseModel):
    server: str | None = Field(None, description="Proxy server address")
    username: Optional[str] = Field(None, description="Proxy username")
    password: Optional[str] = Field(None, description="Proxy password")


class SearchSettings(BaseModel):
    engine: str = Field(default="Google", description="Search engine the llm to use")
    fallback_engines: List[str] = Field(
        default_factory=lambda: ["DuckDuckGo", "Baidu", "Bing"],
        description="Fallback search engines to try if the primary engine fails",
    )
    retry_delay: int = Field(
        default=60,
        description="Seconds to wait before retrying all engines again after they all fail",
    )
    max_retries: int = Field(
        default=3,
        description="Maximum number of times to retry all engines when all fail",
    )
    lang: str = Field(
        default="en",
        description="Language code for search results (e.g., en, zh, fr)",
    )
    country: str = Field(
        default="us",
        description="Country code for search results (e.g., us, cn, uk)",
    )


class RunflowSettings(BaseModel):
    use_data_analysis_agent: bool = Field(
        default=False, description="Enable data analysis agent in run flow"
    )


class BrowserSettings(BaseModel):
    headless: bool = Field(False, description="Whether to run browser in headless mode")
    disable_security: bool = Field(
        True, description="Disable browser security features"
    )
    extra_chromium_args: List[str] = Field(
        default_factory=list, description="Extra arguments to pass to the browser"
    )
    chrome_instance_path: Optional[str] = Field(
        None, description="Path to a Chrome instance to use"
    )
    wss_url: Optional[str] = Field(
        None, description="Connect to a browser instance via WebSocket"
    )
    cdp_url: Optional[str] = Field(
        None, description="Connect to a browser instance via CDP"
    )
    proxy: Optional[ProxySettings] = Field(
        None, description="Proxy settings for the browser"
    )
    max_content_length: int = Field(
        2000, description="Maximum length for content retrieval operations"
    )
    # Optional fields used by browser_use_tool integrations
    engine: str = Field("playwright", description="Browser engine name")
    new_context_config: Optional[object] = Field(
        None, description="Optional BrowserContextConfig or equivalent"
    )


class SandboxSettings(BaseModel):
    """Configuration for the execution sandbox"""

    use_sandbox: bool = Field(False, description="Whether to use the sandbox")
    # Sandbox provider selection: 'local' uses internal Docker sandbox, 'daytona' uses Daytona SDK
    provider: str = Field(
        default="daytona",
        description="Sandbox provider to use: 'local' or 'daytona'",
    )
    # Base image applies to local/docker sandbox implementations
    image: str = Field("python:3.12-slim", description="Base image")
    # Working directory inside the sandbox (both providers should honor this)
    work_dir: str = Field("/home/daytona/workspace", description="Container working directory")
    memory_limit: str = Field("512m", description="Memory limit")
    cpu_limit: float = Field(1.0, description="CPU limit")
    timeout: int = Field(300, description="Default command timeout (seconds)")
    network_enabled: bool = Field(
        False, description="Whether network access is allowed"
    )
    # NEW: control sandbox lifecycle across agent.run invocations
    keep_alive: bool = Field(
        False,
        description="If true, do not automatically cleanup sandbox at the end of agent.run; intended to persist the sandbox across multiple steps/flows in the same conversation.",
    )

    # Daytona-specific optional configuration (can also be set via environment variables)
    api_key: Optional[str] = Field(
        default=None,
        description="Daytona API key (optional if provided via env DAYTONA_API_KEY)",
    )
    api_url: Optional[str] = Field(
        default=None,
        description="Daytona API URL/endpoint (optional if provided via env DAYTONA_API_URL)",
    )
    target: Optional[str] = Field(
        default=None,
        description="Daytona target/region identifier (optional if provided via env DAYTONA_TARGET)",
    )


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server"""

    type: str = Field(..., description="Server connection type (sse or stdio)")
    url: Optional[str] = Field(None, description="Server URL for SSE connections")
    command: Optional[str] = Field(None, description="Command for stdio connections")
    args: List[str] = Field(
        default_factory=list, description="Arguments for stdio command"
    )


class MCPSettings(BaseModel):
    """Configuration for MCP (Model Context Protocol)"""

    server_reference: str = Field(
        "app.mcp.server", description="Module reference for the MCP server"
    )
    servers: Dict[str, MCPServerConfig] = Field(
        default_factory=dict, description="MCP server configurations"
    )

    @classmethod
    def load_server_config(cls) -> Dict[str, MCPServerConfig]:
        """Load MCP server configuration from JSON file"""
        config_path = PROJECT_ROOT / "config" / "mcp.json"

        try:
            config_file = config_path if config_path.exists() else None
            if not config_file:
                return {}

            with config_file.open() as f:
                data = json.load(f)
                servers = {}

                for server_id, server_config in data.get("mcpServers", {}).items():
                    servers[server_id] = MCPServerConfig(
                        type=server_config["type"],
                        url=server_config.get("url"),
                        command=server_config.get("command"),
                        args=server_config.get("args", []),
                    )
                return servers
        except Exception as e:
            raise ValueError(f"Failed to load MCP server config: {e}")


class AppConfig(BaseModel):
    llm: Dict[str, LLMSettings]
    sandbox: Optional[SandboxSettings] = Field(
        None, description="Sandbox configuration"
    )
    browser_config: Optional[BrowserSettings] = Field(
        None, description="Browser configuration"
    )
    search_config: Optional[SearchSettings] = Field(
        None, description="Search configuration"
    )
    mcp_config: Optional[MCPSettings] = Field(None, description="MCP configuration")
    run_flow_config: Optional[RunflowSettings] = Field(
        None, description="Run flow configuration"
    )

    class Config:
        arbitrary_types_allowed = True


class Config:
    _instance = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            with self._lock:
                if not self._initialized:
                    self._config = None
                    self._load_initial_config()
                    self._initialized = True

    def _load_initial_config(self):
        # Build configuration purely from Django settings, do not read config files
        try:
            from django.conf import settings as dj # type: ignore
            is_dj_configured = getattr(dj, "configured", False)
        except Exception:
            dj = None
            is_dj_configured = False

        def dj_get(name: str, default):
            """Safely get a Django setting only if settings are configured."""
            if is_dj_configured:
                try:
                    return getattr(dj, name)
                except Exception:
                    return default
            return default

        # LLM defaults sourced from Django settings when available
        default_settings = {
            "model": dj_get("LLM_MODEL", "deepseek-chat"),
            "base_url": dj_get("LARASANA_API_BASE", "https://api.larasana.com/v1"),
            "api_key": (
                dj_get("LARASANA_API_KEY", None)
                or dj_get("AIMLAPI_KEY", None)
                or "test"
            ),
            "max_tokens": dj_get("LLM_MAX_TOKENS", 4096),
            "max_input_tokens": dj_get("LLM_MAX_INPUT_TOKENS", None),
            "temperature": dj_get("LLM_TEMPERATURE", 1.0),
            "api_type": dj_get("LLM_API_TYPE", "openai"),
            "api_version": dj_get("LLM_API_VERSION", ""),
        }

        # Optional browser config from Django settings as a dict-like
        browser_settings = None
        browser_cfg = dj_get("BROWSER_CONFIG", None)
        if isinstance(browser_cfg, dict) and browser_cfg:
            proxy_cfg = browser_cfg.get("proxy") or {}
            proxy_settings = None
            if isinstance(proxy_cfg, dict) and proxy_cfg.get("server"):
                proxy_settings = ProxySettings(
                    server=proxy_cfg.get("server"),
                    username=proxy_cfg.get("username"),
                    password=proxy_cfg.get("password"),
                )
            browser_settings = BrowserSettings(
                headless=browser_cfg.get("headless", True),
                disable_security=browser_cfg.get("disable_security", True),
                extra_chromium_args=browser_cfg.get("extra_chromium_args", []),
                chrome_instance_path=browser_cfg.get("chrome_instance_path"),
                wss_url=browser_cfg.get("wss_url"),
                cdp_url=browser_cfg.get("cdp_url"),
                proxy=proxy_settings,
                max_content_length=browser_cfg.get("max_content_length", 2000),
                engine=browser_cfg.get("engine", "playwright"),
                new_context_config=browser_cfg.get("new_context_config"),
            )

        # Search settings from Django
        enabled_fallbacks = []
        if dj_get("DUCKDUCKGO_ENABLED", True):
            enabled_fallbacks.append("DuckDuckGo")
        if dj_get("BAIDU_ENABLED", False):
            enabled_fallbacks.append("Baidu")
        if dj_get("BING_ENABLED", False):
            enabled_fallbacks.append("Bing")
        if dj_get("GOOGLE_ENABLED", False):
            enabled_fallbacks.append("Google")
        if dj_get("YAHOO_ENABLED", False):
            enabled_fallbacks.append("Yahoo")

        search_settings = SearchSettings(
            engine=dj_get("SEARCH_ENGINE", "yahoo"),
            fallback_engines=enabled_fallbacks or ["DuckDuckGo", "Baidu", "Bing"],
            retry_delay=dj_get("SEARCH_RETRY_DELAY", 60),
            max_retries=dj_get("SEARCH_MAX_RETRIES", 3),
            lang=dj_get("SEARCH_LANG", "en"),
            country=dj_get("SEARCH_COUNTRY", "us"),
        )

        # Sandbox settings from Django
        sandbox_settings = SandboxSettings(
            use_sandbox=dj_get("SANDBOX_ENABLED", True),
            provider=dj_get("SANDBOX_PROVIDER", "daytona"),
            work_dir=dj_get("SANDBOX_WORK_DIR", str(WORKSPACE_ROOT)),
            image=dj_get("SANDBOX_IMAGE", "python:3.12-slim"),
            memory_limit=dj_get("SANDBOX_MEMORY_LIMIT", "512m"),
            cpu_limit=float(dj_get("SANDBOX_CPU_LIMIT", 1.0)),
            timeout=int(dj_get("SANDBOX_TIMEOUT", 300)),
            network_enabled=bool(dj_get("SANDBOX_NETWORK_ENABLED", True)),
            keep_alive=bool(dj_get("SANDBOX_KEEP_ALIVE", False)),
            api_key=dj_get("DAYTONA_API_KEY", None),
            api_url=dj_get("DAYTONA_API_URL", None),
            target=dj_get("DAYTONA_TARGET", None),
        )

        # MCP settings optional; load JSON if exists
        mcp_servers = MCPSettings.load_server_config()
        mcp_settings = MCPSettings(servers=mcp_servers)

        run_flow_cfg = dj_get("RUNFLOW_CONFIG", None) or {}
        run_flow_settings = RunflowSettings(**run_flow_cfg) if isinstance(run_flow_cfg, dict) else RunflowSettings()

        config_dict = {
            "llm": {
                "default": default_settings,
            },
            "sandbox": sandbox_settings,
            "browser_config": browser_settings,
            "search_config": search_settings,
            "mcp_config": mcp_settings,
            "run_flow_config": run_flow_settings,
        }

        self._config = AppConfig(**config_dict)

    @property
    def llm(self) -> Dict[str, LLMSettings]:
        return self._config.llm

    @property
    def sandbox(self) -> SandboxSettings:
        return self._config.sandbox

    @property
    def browser_config(self) -> Optional[BrowserSettings]:
        return self._config.browser_config

    @property
    def search_config(self) -> Optional[SearchSettings]:
        return self._config.search_config

    @property
    def mcp_config(self) -> MCPSettings:
        """Get the MCP configuration"""
        return self._config.mcp_config

    @property
    def run_flow_config(self) -> RunflowSettings:
        """Get the Run Flow configuration"""
        return self._config.run_flow_config

    @property
    def workspace_root(self) -> str:
        """Get the workspace root directory"""
        return WORKSPACE_ROOT

    @property
    def root_path(self) -> Path:
        """Get the root path of the application"""
        return PROJECT_ROOT


config = Config()
