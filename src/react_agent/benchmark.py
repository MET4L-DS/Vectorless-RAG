import asyncio
import time
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src import retriever
from src import generator
from src import react_agent
from src.retriever import client

console = Console()

TEST_QUERIES = [
    "What is the punishment for robbery?",
    "What if the robber is a minor?",
    "Can you repeat the rule for the maximum detention time?"
]

async def run_benchmark():
    console.print(Panel(
        "[bold yellow]Loading indices for benchmark...[/bold yellow]",
        border_style="yellow"
    ))
    retriever.load("tree")
    
    # 1. Deterministic Pipeline Benchmark
    console.print("\n[bold green]=== RUNNING DETERMINISTIC PIPELINE ===[/bold green]")
    det_history = []
    det_last_retrieval = None
    det_results = []
    
    for q in TEST_QUERIES:
        client.new_calls_count = 0
        start = time.time()
        res = await generator.generate(q, det_history, det_last_retrieval)
        elapsed = round((time.time() - start) * 1000)
        
        det_history.append({"user": q, "assistant": res["answer"]})
        det_last_retrieval = res["retrieval"]
        
        det_results.append({
            "query": q,
            "latency": elapsed,
            "calls": client.new_calls_count,
            "citations": len(res["citations"]),
            "confidence": res["confidence"]
        })
        console.print(f"  - Query: '[dim]{q}[/dim]' -> [green]Done[/green] in {elapsed}ms | LLM Calls: {client.new_calls_count}")
        
    # 2. ReAct Agent Pipeline Benchmark
    console.print("\n[bold magenta]=== RUNNING REACT AGENT PIPELINE ===[/bold magenta]")
    react_history = []
    react_results = []
    
    for q in TEST_QUERIES:
        client.new_calls_count = 0
        start = time.time()
        res = await react_agent.generate(q, react_history)
        elapsed = round((time.time() - start) * 1000)
        
        react_history.append({"user": q, "assistant": res["answer"]})
        
        react_results.append({
            "query": q,
            "latency": elapsed,
            "calls": client.new_calls_count,
            "citations": len(res["citations"]),
            "confidence": res["confidence"]
        })
        console.print(f"  - Query: '[dim]{q}[/dim]' -> [magenta]Done[/magenta] in {elapsed}ms | LLM Calls: {client.new_calls_count}")

        
    # 3. Render Comparison Table
    table = Table(
        title="[bold white]Benchmark Comparison: Deterministic vs ReAct[/bold white]",
        show_header=True,
        header_style="bold cyan",
        border_style="dim white"
    )
    table.add_column("Query Scenario", style="cyan", width=35)
    table.add_column("Det Latency", style="green", justify="right")
    table.add_column("ReAct Latency", style="magenta", justify="right")
    table.add_column("Det Calls", style="green", justify="center")
    table.add_column("ReAct Calls", style="magenta", justify="center")
    table.add_column("Det Citations", style="green", justify="center")
    table.add_column("ReAct Citations", style="magenta", justify="center")
    
    for idx, q in enumerate(TEST_QUERIES):
        d = det_results[idx]
        r = react_results[idx]
        table.add_row(
            q,
            f"{d['latency']} ms",
            f"{r['latency']} ms",
            str(d['calls']),
            str(r['calls']),
            str(d['citations']),
            str(r['citations'])
        )
        
    console.print("\n")
    console.print(table)
    console.print()

if __name__ == "__main__":
    asyncio.run(run_benchmark())
