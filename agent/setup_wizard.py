"""配置向导 — 项目级配置。

行为：
- 进入新项目时，检测 <project>/.coding-agent/config.yaml
- 不存在 → 触发向导
- 向导保存：项目级配置 → <project>/.coding-agent/config.yaml
            API Key     → ~/.coding-agent/credentials.yaml

模型名和 temperature 都不做强制校验：
- 模型名允许任意值
- temperature 允许跳过（不发送该参数）
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from agent.config import global_config_file, project_config_file, save_yaml_config
from agent.credentials import get_api_key, list_providers_with_keys, set_api_key
from agent.providers import PROVIDERS, ProviderInfo


def _ask_model_name(provider: ProviderInfo, console: Console) -> str:
    """询问模型名。

    显示示例模型作为参考，但允许用户输入任意模型名。
    """
    console.print()
    console.print("[bold]选择模型[/bold]")
    console.print("[dim]以下为常用模型（仅供参考）。可输入任意模型名。[/dim]\n")

    if provider.example_models:
        for i, m in enumerate(provider.example_models, 1):
            mark = " [green](默认)[/green]" if m == provider.default_model else ""
            console.print(f"  [cyan]{i:2d}.[/cyan] {m}{mark}")
        console.print()

    manual_idx = len(provider.example_models) + 1
    if provider.example_models:
        console.print(f"  [cyan]{manual_idx:2d}.[/cyan] [bold]手动输入模型名[/bold]")
        console.print()

        default_choice = (
            str(provider.example_models.index(provider.default_model) + 1)
            if provider.default_model in provider.example_models
            else str(manual_idx)
        )

        choice = Prompt.ask(
            "[bold]请选择[/bold]",
            choices=[str(i) for i in range(1, len(provider.example_models) + 2)],
            default=default_choice,
        )

        idx = int(choice)
        if idx <= len(provider.example_models):
            return provider.example_models[idx - 1]
        model = Prompt.ask("[bold]请输入模型名[/bold]").strip()
    else:
        model = Prompt.ask(
            "[bold]请输入模型名[/bold]",
            default=provider.default_model or "",
        ).strip()

    if not model:
        console.print("[red]模型名不能为空[/red]")
        return ""

    return model


def run_setup_wizard(project_path: Path) -> bool:
    """项目级配置向导。"""
    console = Console()
    project_cfg_path = project_config_file(project_path)
    existing_keys = list_providers_with_keys()

    console.print(
        Panel(
            f"[bold cyan]Coding Agent 配置向导[/bold cyan]\n\n"
            f"配置将保存到：[dim]{project_cfg_path}[/dim]\n"
            f"API Key 保存到：[dim]~/.coding-agent/credentials.yaml[/dim]",
            border_style="cyan",
        )
    )

    # ---------- 检测全局配置，问是否复用 ----------
    if global_config_file().exists():
        import yaml

        try:
            global_cfg = yaml.safe_load(global_config_file().read_text(encoding="utf-8")) or {}
        except Exception:
            global_cfg = {}

        if global_cfg:
            console.print()
            console.print("[bold yellow]检测到全局配置:[/bold yellow]")
            for k in ("provider", "model", "base_url"):
                if k in global_cfg:
                    console.print(f"  [dim]{k}:[/dim] {global_cfg[k]}")
            console.print()

            if Confirm.ask(
                "是否直接使用全局配置（复制到当前项目）?",
                default=True,
            ):
                project_cfg = {
                    "provider": global_cfg.get("provider", "qwen"),
                    "langchain_provider": global_cfg.get("langchain_provider", "openai"),
                    "model": global_cfg.get("model", "qwen-max"),
                    "base_url": global_cfg.get("base_url", ""),
                    "timeout": global_cfg.get("timeout", 120),
                    "model_window": global_cfg.get("model_window", 200000),
                }
                # 只在全局配置里明确有 temperature 时才复制
                if "temperature" in global_cfg and global_cfg["temperature"] is not None:
                    project_cfg["temperature"] = global_cfg["temperature"]

                save_yaml_config(project_cfg_path, project_cfg)
                console.print("\n[green]✓[/green] 已复制全局配置到项目")
                console.print(f"[green]✓[/green] 保存到: {project_cfg_path}")
                return True

    # ---------- 选择 Provider ----------
    console.print("\n[bold]可用的模型 Provider:[/bold]\n")
    for i, p in enumerate(PROVIDERS, 1):
        key_note = " [dim](无需 Key)[/dim]" if not p.needs_key else ""
        has_key = " [green]✓ 已保存 Key[/green]" if p.id in existing_keys else ""
        console.print(f"  [cyan]{i:2d}.[/cyan] {p.name}{key_note}{has_key}")

    console.print()
    choice = Prompt.ask(
        "[bold]请选择 Provider[/bold]",
        choices=[str(i) for i in range(1, len(PROVIDERS) + 1)],
        default="1",
    )
    provider = PROVIDERS[int(choice) - 1]

    console.print(f"\n[green]✓[/green] 已选择: [bold]{provider.name}[/bold]")
    if provider.notes:
        console.print(f"[dim]{provider.notes}[/dim]")

    # ---------- API Key ----------
    api_key = ""
    if provider.needs_key:
        existing_key = get_api_key(provider.id)

        if existing_key:
            masked = f"{existing_key[:8]}...{existing_key[-4:]}"
            console.print()
            console.print(f"[dim]检测到已保存的 Key: {masked}[/dim]")
            if Confirm.ask("是否复用该 Key?", default=True):
                api_key = existing_key

        if not api_key:
            if provider.key_url:
                console.print(f"[dim]API Key 申请地址: {provider.key_url}[/dim]")
            api_key = Prompt.ask(
                f"\n[bold]请输入 {provider.env_key}[/bold]",
                password=True,
            ).strip()
            if not api_key:
                console.print("[red]API Key 不能为空[/red]")
                return False
            set_api_key(provider.id, api_key)
            console.print("[green]✓[/green] Key 已保存到全局凭据")

    # ---------- 选择模型名 ----------
    model = _ask_model_name(provider, console)
    if not model:
        return False

    # ---------- base_url ----------
    base_url = provider.base_url
    if provider.id == "custom" or not base_url:
        console.print()
        base_url = Prompt.ask(
            "[bold]请输入 API Base URL[/bold]",
            default=base_url or "",
        ).strip()
        if not base_url:
            console.print("[red]Base URL 不能为空[/red]")
            return False

    # ---------- temperature（可选）----------
    console.print()
    console.print("[bold]temperature 设置[/bold]")
    console.print(
        "[dim]某些模型（如 kimi-k3、deepseek-reasoner、o1）"
        "不接受 temperature 参数。\n"
        "如果不确定，选 N（不发送该参数）。[/dim]\n"
    )

    if Confirm.ask("[bold]是否设置 temperature?[/bold]", default=False):
        try:
            temperature = float(Prompt.ask("temperature (0.0 - 2.0)", default="0.7"))
            if temperature < 0 or temperature > 2:
                console.print("[yellow]超出范围，改为不发送[/yellow]")
                temperature = None
        except ValueError:
            console.print("[yellow]无效值，改为不发送[/yellow]")
            temperature = None
    else:
        temperature = None

    if temperature is None:
        console.print("[dim]→ temperature 将不发送[/dim]")
    else:
        console.print(f"[dim]→ temperature = {temperature}[/dim]")

    # ---------- 其他高级选项 ----------
    console.print()
    if Confirm.ask(
        "[bold]是否配置 timeout 和 model_window?[/bold]",
        default=False,
    ):
        try:
            timeout = int(Prompt.ask("timeout (秒)", default="120"))
            model_window = int(Prompt.ask("model_window (tokens)", default="200000"))
        except ValueError:
            console.print("[yellow]数值格式错误，使用默认值[/yellow]")
            timeout, model_window = 120, 200000
    else:
        timeout, model_window = 120, 200000

    # ---------- 保存项目级配置 ----------
    project_cfg = {
        "provider": provider.id,
        "langchain_provider": provider.langchain_provider,
        "model": model,
        "base_url": base_url,
        "timeout": timeout,
        "model_window": model_window,
    }
    # 只有明确设置时才写入 temperature
    if temperature is not None:
        project_cfg["temperature"] = temperature

    save_yaml_config(project_cfg_path, project_cfg)
    console.print(f"\n[green]✓[/green] 项目配置已保存: {project_cfg_path}")

    # ---------- 测试连接 ----------
    console.print()
    if Confirm.ask("[bold]是否测试连接?[/bold]", default=True):
        _test_connection(provider, model, base_url, api_key, console, temperature)

    console.print("\n[bold green]配置完成！[/bold green]")
    return True


def _test_connection(
    provider: ProviderInfo,
    model: str,
    base_url: str,
    api_key: str,
    console: Console,
    temperature: float | None = None,
) -> bool:
    """测试模型连接。"""
    console.print("[dim]正在测试连接...[/dim]")

    try:
        if provider.langchain_provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            kwargs: dict = {
                "model": model,
                "api_key": api_key,
                "timeout": 30,
            }
            if temperature is not None:
                kwargs["temperature"] = temperature
            llm = ChatAnthropic(**kwargs)
        else:
            from langchain_openai import ChatOpenAI

            kwargs = {
                "model": model,
                "api_key": api_key or "dummy",
                "base_url": base_url,
                "timeout": 30,
            }
            if temperature is not None:
                kwargs["temperature"] = temperature
            llm = ChatOpenAI(**kwargs)

        resp = llm.invoke("回复 OK 两个字")
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        console.print(f"[green]✓ 连接成功[/green] 模型回复: {content[:50]}")
        return True
    except Exception as e:
        console.print(f"[red]✗ 连接失败: {type(e).__name__}: {e}[/red]")
        console.print("[dim]配置已保存。可稍后重新运行 `coding-agent init`[/dim]")
        return False


def maybe_run_first_time_setup(project_path: Path) -> bool:
    """项目级首次检测。"""
    if project_config_file(project_path).exists():
        return False

    console = Console()
    console.print(
        Panel(
            f"[yellow]当前项目未配置模型[/yellow]\n\n"
            f"项目: {project_path}\n"
            f"将为该项目配置 Provider、API Key 和模型。",
            border_style="yellow",
        )
    )
    console.print()
    return run_setup_wizard(project_path)
