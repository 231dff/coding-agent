"""支持的模型 Provider 定义。

设计原则：
- Provider 定义只声明 base_url、env_key、langchain_provider 等元信息
- models 列表仅作 UI 提示，不是白名单
- 用户可以在向导中手动输入任意模型名，不做校验
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProviderInfo:
    id: str
    name: str
    langchain_provider: str  # openai / anthropic
    base_url: str = ""
    env_key: str = ""
    default_model: str = ""
    # 常见的模型名作为 UI 提示；用户可输入任意模型名
    example_models: list[str] = field(default_factory=list)
    needs_key: bool = True
    key_url: str = ""
    notes: str = ""


PROVIDERS: list[ProviderInfo] = [
    ProviderInfo(
        id="qwen",
        name="通义千问 (阿里云百炼)",
        langchain_provider="openai",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        env_key="DASHSCOPE_API_KEY",
        default_model="qwen-max",
        example_models=[
            "qwen-max",
            "qwen-max-latest",
            "qwen-plus",
            "qwen-turbo",
            "qwen3-max",
            "qwen3.8-max-0902",
            "qwen2.5-72b-instruct",
        ],
        key_url="https://bailian.console.aliyun.com/",
        notes="可输入任意 DashScope 模型名",
    ),
    ProviderInfo(
        id="openai",
        name="OpenAI",
        langchain_provider="openai",
        base_url="https://api.openai.com/v1",
        env_key="OPENAI_API_KEY",
        default_model="gpt-4o",
        example_models=[
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "o1",
            "o1-mini",
            "o3-mini",
        ],
        key_url="https://platform.openai.com/api-keys",
    ),
    ProviderInfo(
        id="anthropic",
        name="Anthropic Claude",
        langchain_provider="anthropic",
        env_key="ANTHROPIC_API_KEY",
        default_model="claude-sonnet-4-5",
        example_models=[
            "claude-sonnet-4-5",
            "claude-opus-4-5",
            "claude-haiku-4-5",
            "claude-3-5-sonnet-20241022",
        ],
        key_url="https://console.anthropic.com/",
        notes="使用 Anthropic 原生接口",
    ),
    ProviderInfo(
        id="deepseek",
        name="DeepSeek",
        langchain_provider="openai",
        base_url="https://api.deepseek.com/v1",
        env_key="DEEPSEEK_API_KEY",
        default_model="deepseek-chat",
        example_models=[
            "deepseek-chat",
            "deepseek-reasoner",
            "deepseek-coder",
        ],
        key_url="https://platform.deepseek.com/",
    ),
    ProviderInfo(
        id="moonshot",
        name="Moonshot / Kimi",
        langchain_provider="openai",
        base_url="https://api.moonshot.cn/v1",
        env_key="MOONSHOT_API_KEY",
        default_model="moonshot-v1-128k",
        example_models=[
            "moonshot-v1-8k",
            "moonshot-v1-32k",
            "moonshot-v1-128k",
            "kimi-k2",
        ],
        key_url="https://platform.moonshot.cn/",
    ),
    ProviderInfo(
        id="zhipu",
        name="智谱 GLM",
        langchain_provider="openai",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        env_key="ZHIPU_API_KEY",
        default_model="glm-4-plus",
        example_models=[
            "glm-4-plus",
            "glm-4",
            "glm-4-flash",
            "glm-4-air",
        ],
        key_url="https://open.bigmodel.cn/",
    ),
    ProviderInfo(
        id="gemini",
        name="Google Gemini",
        langchain_provider="openai",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        env_key="GOOGLE_API_KEY",
        default_model="gemini-2.5-pro",
        example_models=[
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
        ],
        key_url="https://aistudio.google.com/apikey",
    ),
    ProviderInfo(
        id="openrouter",
        name="OpenRouter (聚合)",
        langchain_provider="openai",
        base_url="https://openrouter.ai/api/v1",
        env_key="OPENROUTER_API_KEY",
        default_model="anthropic/claude-sonnet-4-5",
        example_models=[
            "anthropic/claude-sonnet-4-5",
            "openai/gpt-4o",
            "google/gemini-2.5-pro",
            "deepseek/deepseek-chat",
            "qwen/qwen-max",
        ],
        key_url="https://openrouter.ai/keys",
        notes="可输入 OpenRouter 上任意模型（格式: provider/model）",
    ),
    ProviderInfo(
        id="ollama",
        name="Ollama (本地)",
        langchain_provider="openai",
        base_url="http://localhost:11434/v1",
        env_key="OLLAMA_API_KEY",
        default_model="qwen2.5:14b",
        example_models=[
            "qwen2.5:14b",
            "qwen2.5:32b",
            "llama3.3:70b",
            "deepseek-r1:14b",
        ],
        needs_key=False,
        key_url="https://ollama.com/",
        notes="本地部署，不需要 API Key；输入 `ollama list` 查看已下载的模型",
    ),
    ProviderInfo(
        id="custom",
        name="自定义 OpenAI 兼容接口",
        langchain_provider="openai",
        env_key="CUSTOM_API_KEY",
        default_model="",
        example_models=[],
        notes="任意 OpenAI 兼容端点（自建 vLLM、企业内部代理等）",
    ),
]


def get_provider(provider_id: str) -> ProviderInfo | None:
    for p in PROVIDERS:
        if p.id == provider_id:
            return p
    return None
