import asyncio
import os
import sys
import time
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
from langgraph.checkpoint.memory import MemorySaver

from src import retriever
from src.retriever import graph
from src.react_agent.agent import get_agent
from src.retriever import client

console = Console()
LOCAL_AGENT = get_agent(MemorySaver())


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
                
            # Reset metrics tracking for this query
            client.new_calls_count = 0
            client.call_history.clear()
            start_time = time.time()
            
            # 1. Format history messages
            messages = []
            for turn in history:
                messages.append(HumanMessage(content=turn.get("user", "")))
                assistant_clean = turn.get("assistant", "").split("[References]")[0].strip()
                messages.append(AIMessage(content=assistant_clean))
            messages.append(HumanMessage(content=query))
            
            # Setup checkpointer configuration
            thread_id = f"cli_{int(time.time())}"
            config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 10}
            
            # If trace mode is ON, we stream updates to show the Thought-Action-Observation loop
            if trace_mode:
                console.print(f"\n[bold yellow]Agent is reasoning...[/bold yellow]")
                
                # 2. Run streaming graph
                try:
                    async for chunk in LOCAL_AGENT.astream(
                        {"messages": messages}, 
                        config=config, 
                        stream_mode=["updates", "custom"],
                        version="v2"
                    ):
                        chunk_type = chunk.get("type")
                        chunk_data = chunk.get("data")
                        
                        if chunk_type == "custom":
                            # Stream writer custom status update
                            msg_text = chunk_data.get("message", "")
                            if msg_text:
                                # Strip emojis and non-ASCII characters to prevent Windows console encoding crashes
                                clean_msg = msg_text.encode('ascii', errors='ignore').decode('ascii').strip()
                                clean_msg = " ".join(clean_msg.split())
                                if clean_msg:
                                    console.print(f"[dim cyan]  -> {clean_msg}[/dim cyan]")
                        
                        elif chunk_type == "updates" and isinstance(chunk_data, dict):
                            for node, update in chunk_data.items():
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
            
            else:
                # If trace mode is OFF, run the graph to completion in the background
                with console.status("[bold yellow]Executing agent reasoning...[/bold yellow]", spinner="dots"):
                    await LOCAL_AGENT.ainvoke({"messages": messages}, config=config)

            # 3. Retrieve final state to extract the structured answer
            state = await LOCAL_AGENT.aget_state(config)
            generated = state.values.get("structured_response")
            
            if not generated:
                res = {
                    "answer": "Error: No structured answer was generated by the agent.",
                    "confidence": 0.0,
                    "latency_ms": round((time.time() - start_time) * 1000)
                }
            else:
                # Resolve citation dictionaries from keys
                citations_list = []
                if generated.citations:
                    for cid in generated.citations:
                        node = graph._corpus_index.get_node(cid) if graph._corpus_index else None
                        if node:
                            citations_list.append({
                                "node_id": cid,
                                "act_code": cid.split("_")[0],
                                "title": node.get("title", ""),
                                "quoted_text": "",
                                "page_range": node.get("metadata", {}).get("page_range", [])
                            })
                            
                # Construct final answer markdown exactly matching the state machine layout
                lines = []
                lines.append("[Answer]")
                lines.append(generated.answer_text)
                lines.append("")
                
                if generated.key_provisions:
                    lines.append("[Key Provisions]")
                    for provision in generated.key_provisions:
                        p_strip = provision.strip()
                        if not p_strip.startswith("-"):
                            p_strip = f"- {p_strip}"
                        lines.append(p_strip)
                    lines.append("")
                    
                if citations_list:
                    lines.append("[References]")
                    for idx, citation in enumerate(citations_list):
                        lines.append(f"[{idx+1}] {citation['node_id']}: {citation['title']}")
                        
                final_ans = "\n".join(lines).strip()
                res = {
                    "answer": final_ans,
                    "confidence": 0.0 if generated.is_insufficient_context else 1.0,
                    "latency_ms": round((time.time() - start_time) * 1000)
                }

            # 4. Print Response Metadata & API Call Pacing Profile Table
            conf_badge = "[bold green][OK] ADEQUATE CONTEXT[/bold green]" if res["confidence"] > 0 else "[bold red][FAIL] INSUFFICIENT CONTEXT[/bold red]"
            border_color = "green" if res["confidence"] > 0 else "red"
            
            console.print(Panel(
                f"Status: {conf_badge}\nLatency: [cyan]{res['latency_ms']}[/cyan] ms",
                title="[bold white]Response Metadata[/bold white]",
                border_style=border_color,
                expand=False
            ))
            console.print()

            if client.call_history:
                table = Table(title="[bold cyan]LLM API Call Profile[/bold cyan]", border_style="cyan", show_header=True)
                table.add_column("Call #", justify="right", style="dim")
                table.add_column("Model Name", style="cyan")
                table.add_column("Type/Description", style="magenta")
                table.add_column("Response Time", justify="right", style="green")
                
                total_retriever_time = 0.0
                for idx, call in enumerate(client.call_history):
                    elapsed = call["elapsed"]
                    total_retriever_time += elapsed
                    table.add_row(
                        str(idx + 1),
                        call["model"].replace("models/", ""),
                        call["description"],
                        f"{elapsed:.2f}s"
                    )
                console.print(table)
                console.print(f"[bold cyan]Total LLM Retriever Calls:[/bold cyan] {client.new_calls_count} | [bold cyan]Accumulated Retriever Time:[/bold cyan] {total_retriever_time:.2f}s\n")
            
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
