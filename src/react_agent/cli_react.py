import asyncio
import os
import sys
# Add project root to path to resolve 'src' imports when run directly
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from collections import deque
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text
from rich.align import Align
from langchain_core.messages import HumanMessage, AIMessage

from src import retriever
from src.retriever import graph
from src.react_agent.agent import COMPILED_AGENT
from src.react_agent import generate

console = Console()

async def main():
    console.print(Panel(
        Align.center("[bold magenta]Vectorless-RAG ReAct Agent Assistant[/bold magenta]\n"
                     "[dim white]Autonomous Thought -> Action -> Observation loop[/dim white]"),
        border_style="magenta"
    ))
    
    console.print("[bold yellow]Loading indices...[/bold yellow]")
    retriever.load("tree")
    console.print()
    
    console.print(Panel(
        "[bold green]Ready![/bold green] Ask a legal scenario. The agent will autonomously decide what to search.\n\n"
        "[bold white]Commands:[/bold white]\n"
        "  [cyan]exit[/cyan] / [cyan]quit[/cyan] - Close assistant\n"
        "  [cyan]clear[/cyan]       - Clear chat memory\n"
        "  [cyan]trace[/cyan]       - Toggle verbose reasoning trace (currently ON)",
        title="[bold magenta]ReAct System Status[/bold magenta]",
        border_style="magenta",
        expand=False
    ))
    console.print()
    
    MEMORY_LIMIT = 5
    history = deque(maxlen=MEMORY_LIMIT)
    trace_mode = True
    
    while True:
        try:
            query = console.input("[bold deep_sky_blue1]Query > [/bold deep_sky_blue1]")
            if query.strip().lower() in ['exit', 'quit', 'q']:
                break
            if query.strip().lower() == 'clear':
                history.clear()
                console.print("[bold green]Memory cleared![/bold green]\n")
                continue
            if query.strip().lower() == 'trace':
                trace_mode = not trace_mode
                status = "ENABLED" if trace_mode else "DISABLED"
                console.print(f"[bold yellow]Trace logs {status}.[/bold yellow]\n")
                continue
                
            if not query.strip():
                continue
                
            # If trace mode is ON, we stream updates to show the Thought-Action-Observation loop
            if trace_mode:
                console.print(f"\n[bold yellow]Agent is reasoning...[/bold yellow]")
                
                # 1. Format history messages
                messages = []
                for turn in history:
                    messages.append(HumanMessage(content=turn.get("user", "")))
                    assistant_clean = turn.get("assistant", "").split("[References]")[0].strip()
                    messages.append(AIMessage(content=assistant_clean))
                messages.append(HumanMessage(content=query))
                
                # 2. Run streaming graph
                try:
                    async for event in COMPILED_AGENT.astream(
                        {"messages": messages}, 
                        config={"recursion_limit": 10}, 
                        stream_mode="updates"
                    ):
                        for node, update in event.items():
                            if node == "agent":
                                msgs = update.get("messages", [])
                                if msgs:
                                    msg = msgs[-1]
                                    
                                    # Handle list content in agent thoughts
                                    content = msg.content
                                    if isinstance(content, list):
                                        parts = []
                                        for part in content:
                                            if isinstance(part, str):
                                                parts.append(part)
                                            elif isinstance(part, dict) and "text" in part:
                                                parts.append(part["text"])
                                            elif hasattr(part, "text"):
                                                parts.append(part.text)
                                        content = "".join(parts)
                                        
                                    if content:
                                        console.print(Panel(
                                            content.strip(), 
                                            title="[bold yellow]Agent Thought[/bold yellow]", 
                                            border_style="yellow"
                                        ))

                                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                                        for tc in msg.tool_calls:
                                            console.print(f"[bold cyan]Action (Call Tool):[/bold cyan] [bold white]{tc['name']}[/bold white] with args: [magenta]{tc['args']}[/magenta]")
                            elif node == "tools":
                                msgs = update.get("messages", [])
                                if msgs:
                                    msg = msgs[-1]
                                    
                                    # Handle list content in tool observations
                                    content = msg.content
                                    if isinstance(content, list):
                                        parts = []
                                        for part in content:
                                            if isinstance(part, str):
                                                parts.append(part)
                                            elif isinstance(part, dict) and "text" in part:
                                                parts.append(part["text"])
                                            elif hasattr(part, "text"):
                                                parts.append(part.text)
                                        content = "".join(parts)
                                        
                                    preview = content[:300] + "..." if len(content) > 300 else content
                                    console.print(Panel(
                                        preview.strip(), 
                                        title="[bold green]Observation (Tool Output)[/bold green]", 
                                        border_style="green"
                                    ))
                                    console.print()
                except Exception as e:
                    console.print(f"\n[bold red]Trace Loop Error: {e}[/bold red]\n")
            
            # 3. Call standard generate interface to get final formatted answer & metadata
            with console.status("[bold yellow]Synthesizing final structured response...[/bold yellow]", spinner="dots"):
                res = await generate(
                    query=query,
                    history=list(history),
                )
            
            # 4. Print Response Metadata (ASCII only to prevent Windows console encoding crash)
            conf_badge = "[bold green][OK] ADEQUATE CONTEXT[/bold green]" if res["confidence"] > 0 else "[bold red][FAIL] INSUFFICIENT CONTEXT[/bold red]"
            border_color = "green" if res["confidence"] > 0 else "red"
            
            console.print(Panel(
                f"Status: {conf_badge}\nLatency: [cyan]{res['latency_ms']}[/cyan] ms",
                title="[bold white]Response Metadata[/bold white]",
                border_style=border_color,
                expand=False
            ))
            console.print()

            
            # 5. Print Answer using Markdown
            console.print(Panel(
                Markdown(res.get('answer', '')),
                title="[bold magenta]ReAct Final Answer[/bold magenta]",
                border_style="magenta"
            ))
            console.print()
            
            # Add to memory
            history.append({
                "user": query,
                "assistant": res.get("answer", "")
            })
            
            console.print("[dim white]" + "="*60 + "[/dim white]\n")
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            console.print(f"\n[bold red]Error: {e}[/bold red]\n")

if __name__ == "__main__":
    asyncio.run(main())
