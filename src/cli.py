import asyncio
import os
import sys
# Add project root to path to resolve 'src' imports when run directly
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from collections import deque
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text
from rich.align import Align

from src import retriever
from src import generator

console = Console()

async def main():
    console.print(Panel(
        Align.center("[bold cyan]Vectorless-RAG Legal Conversational Assistant[/bold cyan]\n"
                     "[dim white]Multi-turn statutory & SOP query resolver[/dim white]"),
        border_style="cyan"
    ))
    
    console.print("[bold yellow]Loading indices...[/bold yellow]")
    retriever.load("tree")
    console.print()
    
    console.print(Panel(
        "[bold green]Ready![/bold green] Type your legal query below.\n\n"
        "[bold white]Commands:[/bold white]\n"
        "  [cyan]exit[/cyan] / [cyan]quit[/cyan] - Close assistant\n"
        "  [cyan]clear[/cyan]       - Clear chat memory & cached context\n"
        "  [cyan]debug[/cyan]       - Toggle retrieval debug trace logs",
        title="[bold cyan]System Status[/bold cyan]",
        border_style="green",
        expand=False
    ))
    console.print()
    
    # Configure conversation history window (Configurable turn count)
    MEMORY_LIMIT = 5
    history = deque(maxlen=MEMORY_LIMIT)
    last_retrieval = None
    debug_mode = False
    
    while True:
        try:
            query = console.input("[bold deep_sky_blue1]Query > [/bold deep_sky_blue1]")
            if query.strip().lower() in ['exit', 'quit', 'q']:
                break
            if query.strip().lower() == 'clear':
                history.clear()
                last_retrieval = None
                console.print("[bold green]Memory and retrieved context cleared![/bold green]\n")
                continue
            if query.strip().lower() == 'debug':
                debug_mode = not debug_mode
                status = "ENABLED" if debug_mode else "DISABLED"
                console.print(f"[bold yellow]Debug traces {status}.[/bold yellow]\n")
                continue
                
            if not query.strip():
                continue
                
            # Call stateful Generation & Verifier Graph wrapped in spinner
            with console.status("[bold yellow]Processing...[/bold yellow]", spinner="dots"):
                res = await generator.generate(
                    query=query,
                    history=list(history),
                    last_retrieval=last_retrieval
                )
            
            # Save retrieval result in cache
            last_retrieval = res.get("retrieval")
            
            # 1. Print Response Metadata Panel
            conf = res.get("confidence", 0.0)
            latency = res.get("latency_ms", 0)
            if conf >= 0.90:
                badge = f"[bold green][OK] HIGH CONFIDENCE ({conf:.2f})[/bold green]"
                border_color = "green"
            elif conf >= 0.70:
                badge = f"[bold yellow][WARN] MEDIUM CONFIDENCE ({conf:.2f})[/bold yellow]"
                border_color = "yellow"
            else:
                badge = f"[bold red][FAIL] LOW CONFIDENCE ({conf:.2f})[/bold red]"
                border_color = "red"
                
            console.print(Panel(
                f"Status: {badge}\nLatency: [cyan]{latency}[/cyan] ms",
                title="[bold white]Response Metadata[/bold white]",
                border_style=border_color,
                expand=False
            ))
            console.print()
            
            # 2. Print Answer using Markdown
            console.print(Panel(
                Markdown(res.get('answer', '')),
                title="[bold green]Assistant Answer[/bold green]",
                border_style="green"
            ))
            console.print()
            
            # 3. Print citations & references if in debug mode
            if debug_mode and last_retrieval:
                meta = last_retrieval.get("query_metadata", {})
                table = Table(title="Retrieval Debug Info", border_style="magenta", show_header=True)
                table.add_column("Metric", style="cyan")
                table.add_column("Value", style="magenta")
                
                table.add_row("Target Corpora", str(meta.get('target_corpora', [])))
                table.add_row("BM25 Hits", str(meta.get('bm25_hits', 0)))
                table.add_row("Tree Hits", str(meta.get('tree_hits', 0)))
                table.add_row("Cross Ref Hits", str(meta.get('cross_ref_enrichment_count', meta.get('cross_ref_hits', 0))))
                table.add_row("Unique Nodes Matched", str(meta.get('total_unique_hits', 0)))
                
                console.print(table)
                console.print()
                
            # Add turn to rolling history
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
