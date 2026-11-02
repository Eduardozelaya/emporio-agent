"""Interactive chat.

Deliberately thin: it reads a line, calls `agent.run_turn`, prints the answer. All the
business logic is behind that call, so replacing this file with a WhatsApp webhook or an HTTP
endpoint would not touch anything else.

`/debug` is the reason an evaluator should prefer this over a web UI: it shows which tools ran
with which arguments, which is the clearest evidence that the agent knows when to query data
and when to answer from the policies.
"""

from __future__ import annotations

import json

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from emporio import agent, memory, store_hours
from emporio.config import Settings, get_settings, now
from emporio.db import DatabaseMissingError

MAX_INPUT_CHARS = 2000

HELP = """\
`/debug`   mostra as ferramentas chamadas em cada resposta
`/new`     começa uma conversa nova
`/session` mostra o id desta conversa
`/help`    esta ajuda
`/exit`    sair (Ctrl+C também funciona)\
"""


def _banner(console: Console, session_id: str, settings: Settings, resumed: int) -> None:
    status = store_hours.status(now())
    lines = [
        "[bold]Empório da Música[/bold] — atendimento",
        f"[dim]{status.reason}[/dim]",
        "",
        f"sessão [cyan]{session_id}[/cyan]"
        + (f"  ·  {resumed} mensagens recuperadas" if resumed else ""),
        f"modelo [cyan]{settings.llm_model}[/cyan]",
        "",
        "[dim]/help para os comandos, /exit para sair[/dim]",
    ]
    console.print(Panel("\n".join(lines), border_style="yellow", expand=False))


def _print_tools(console: Console, reply: agent.Reply) -> None:
    if not reply.tool_calls:
        console.print("[dim]  (nenhuma ferramenta — respondido a partir do manual)[/dim]")
        return
    for call in reply.tool_calls:
        arguments = json.dumps(call.arguments, ensure_ascii=False)
        marker = "[red]✗[/red]" if call.failed else "[green]✓[/green]"
        console.print(f"  {marker} [cyan]{call.name}[/cyan][dim]({arguments})[/dim]")
        summary = call.result.get("error") or _summarise(call.result)
        console.print(f"     [dim]→ {summary}[/dim]")


def _summarise(result: dict) -> str:
    """One line about what a tool returned, so /debug stays readable."""
    if "items" in result:
        return f"{result.get('total_found', len(result['items']))} resultado(s)"
    if "product" in result:
        return f"{result['product']['name']} — R$ {result['product']['price']:.2f}"
    if "matches" in result:
        return f"{len(result['matches'])} correspondências (ambíguo)"
    if "order" in result:
        order = result["order"]
        flag = " [needs_attention]" if order.get("needs_attention") else ""
        return f"pedido {order['order_id']}: {order['status_label_pt']}{flag}"
    if "final_total" in result:
        return f"total R$ {result['final_total']:.2f}"
    if "ticket_id" in result:
        return f"chamado #{result['ticket_id']}"
    return "ok"


def run(session_id: str | None = None, debug: bool = False) -> int:
    console = Console()
    settings = get_settings()

    try:
        settings.require_api_key()
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    resumed = 0
    if session_id:
        resumed = memory.message_count(session_id, settings)
        if not resumed:
            console.print(
                f"[yellow]Sessão '{session_id}' não encontrada. Criando uma nova.[/yellow]"
            )
            session_id = memory.new_session_id()
    else:
        session_id = memory.new_session_id()

    _banner(console, session_id, settings, resumed)

    while True:
        try:
            text = console.input("[bold green]você[/bold green] › ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Até mais![/dim]")
            return 0

        if not text:
            continue

        if text.startswith("/"):
            command = text.lower()
            if command in ("/exit", "/quit", "/sair"):
                console.print("[dim]Até mais![/dim]")
                return 0
            if command == "/help":
                console.print(Markdown(HELP))
                continue
            if command == "/debug":
                debug = not debug
                console.print(f"[dim]debug {'ligado' if debug else 'desligado'}[/dim]")
                continue
            if command == "/new":
                session_id = memory.new_session_id()
                console.print(f"[dim]nova sessão: {session_id}[/dim]")
                continue
            if command == "/session":
                console.print(f"[dim]sessão atual: {session_id}[/dim]")
                continue
            console.print(f"[yellow]Comando desconhecido: {text}. Use /help.[/yellow]")
            continue

        if len(text) > MAX_INPUT_CHARS:
            console.print(
                f"[yellow]Mensagem muito longa, cortando em {MAX_INPUT_CHARS} caracteres.[/yellow]"
            )
            text = text[:MAX_INPUT_CHARS]

        try:
            history = memory.load_window(session_id, settings=settings)
            with console.status("[dim]consultando…[/dim]"):
                reply = agent.run_turn(session_id, text, settings, history=history)
            memory.append(session_id, reply.messages, settings)
        except DatabaseMissingError as exc:
            console.print(f"[red]{exc}[/red]")
            return 1

        if debug:
            _print_tools(console, reply)
            console.print(
                f"[dim]  {reply.usage.prompt_tokens} tokens in / "
                f"{reply.usage.completion_tokens} out · {reply.latency_s}s"
                + (f" · fallback: {reply.error}" if reply.error else "")
                + "[/dim]"
            )

        console.print("[bold yellow]loja[/bold yellow] › ", end="")
        console.print(Markdown(reply.text))
        console.print()
