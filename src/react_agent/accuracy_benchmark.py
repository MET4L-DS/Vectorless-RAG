import asyncio
import json
import time
import os
import sys
from pydantic import BaseModel
from typing import List

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src import retriever
from src import react_agent
from src.retriever import client
from src.summarizer import call_model as call_gemma_model

console = Console()

DATASET_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "tests", "benchmark_data", "indian_criminal_law_golden_answers.json"
)

# A structured prompt for the Gemma model acting as comparator
COMPARATOR_PROMPT_TEMPLATE = """
You are an expert legal evaluator. Your task is to compare an 'Agent Answer' against a 'Golden Truth Answer'.
You must evaluate two criteria:
1. Completeness: Does the Agent Answer contain the core substantive facts and correct primary legal provisions present in the Golden Truth? (Yes/No)
2. Contradiction: Does the Agent Answer contradict any facts stated in the Golden Truth? Or does it cite incorrect, inapplicable, or weaker-nexus statutory provisions (e.g., citing PCA Section 11 instead of the correct primary offense Section 7 specified in the Golden Truth)? If the Agent Answer relies on or asserts wrong/weak section numbers/offenses compared to the Golden Truth, evaluate this as Contradiction: Yes. (Yes/No)

[Golden Truth Answer]
{golden_answer}

[Agent Answer]
{agent_answer}

Provide your evaluation in the following strict format:
Completeness: [Yes/No]
Contradiction: [Yes/No]
Reasoning: [Brief explanation]
"""

async def call_gemma_comparator_with_retry(prompt: str, retries: int = 5) -> str:
    for attempt in range(retries):
        try:
            return await call_gemma_model(prompt)
        except Exception as e:
            console.print(f"[yellow]Gemma comparator call failed (attempt {attempt+1}/{retries}): {e}[/yellow]")
            if attempt == retries - 1:
                raise e
            # Exponential backoff plus safety delay
            await asyncio.sleep(2 ** attempt + 5)

async def run_accuracy_benchmark():
    if not os.path.exists(DATASET_PATH):
        console.print(f"[bold red]Dataset not found at {DATASET_PATH}[/bold red]")
        return
        
    with open(DATASET_PATH, 'r', encoding='utf-8') as f:
        dataset = json.load(f)
        
    console.print(Panel(
        "[bold yellow]Loading indices for accuracy benchmark...[/bold yellow]",
        border_style="yellow"
    ))
    retriever.load("tree")
    
    console.print(f"\n[bold magenta]=== RUNNING REACT AGENT ACCURACY BENCHMARK ({len(dataset)} cases) ===[/bold magenta]")
    
    results = []
    
    table = Table(
        title="[bold white]Accuracy Benchmark Results[/bold white]",
        show_header=True,
        header_style="bold cyan",
        border_style="dim white"
    )
    table.add_column("ID", style="cyan")
    table.add_column("Category", style="yellow")
    table.add_column("Recall", style="green", justify="center")
    table.add_column("Completeness", style="magenta", justify="center")
    table.add_column("Contradiction", style="red", justify="center")
    
    for i, case in enumerate(dataset):
        case_id = case["id"]
        query = case["query"]
        expected_acts = case["expected_citations"]
        golden_answer = case.get("golden_answer", "").strip()
        
        if not golden_answer:
            console.print(f"[bold yellow]Skipping {case_id}: No golden answer provided.[/bold yellow]")
            table.add_row(case_id, case["category"], "SKIP", "SKIP", "SKIP")
            continue
            
        # Throttling to enforce 12 RPM safety pace for ReAct generation
        if i > 0:
            console.print(f"[dim]Throttling for 12 RPM rate limit... sleeping 5 seconds[/dim]")
            await asyncio.sleep(5.0)

        client.new_calls_count = 0
        console.print(f"\n[bold blue]Evaluating {case_id}...[/bold blue]")
        console.print(f"Query: [dim]{query}[/dim]")
        
        start = time.time()
        # Ensure we pass a fresh history for each standalone query
        res = await react_agent.generate(query, [])
        elapsed = round((time.time() - start) * 1000)
        
        agent_answer = res["answer"]
        citations = res["citations"]
        
        # 1. Evaluate Citation Recall (Act-level)
        cited_acts = set([cit["act_code"] for cit in citations])
        recall_passed = True
        missing_acts = []
        for expected_act in expected_acts:
            if expected_act not in cited_acts:
                recall_passed = False
                missing_acts.append(expected_act)
                
        recall_str = "[green]PASS[/green]" if recall_passed else f"[red]FAIL[/red] (Missing: {','.join(missing_acts)})"
        
        # 2. Evaluate using Gemma Comparator
        prompt = COMPARATOR_PROMPT_TEMPLATE.format(
            golden_answer=golden_answer,
            agent_answer=agent_answer
        )
        
        console.print(f"Calling Gemma comparator for {case_id}...")
        eval_result = await call_gemma_comparator_with_retry(prompt)
        
        # Parse the output
        is_complete = "No"
        has_contradiction = "Yes"
        
        for line in eval_result.split("\n"):
            line = line.strip().lower()
            if line.startswith("completeness:"):
                is_complete = "Yes" if "yes" in line else "No"
            elif line.startswith("contradiction:"):
                has_contradiction = "Yes" if "yes" in line else "No"
                
        comp_str = "[green]Yes[/green]" if is_complete == "Yes" else "[red]No[/red]"
        contr_str = "[green]No[/green]" if has_contradiction == "No" else "[red]Yes[/red]"
        
        table.add_row(case_id, case["category"], recall_str, comp_str, contr_str)
        
        results.append({
            "id": case_id,
            "category": case["category"],
            "query": query,
            "golden_answer": golden_answer,
            "agent_answer": agent_answer,
            "latency_ms": elapsed,
            "recall": recall_passed,
            "missing_acts": missing_acts,
            "is_complete": is_complete == "Yes",
            "has_contradiction": has_contradiction == "Yes",
            "gemma_evaluation": eval_result
        })
        
        console.print(f"Done in {elapsed}ms | Recall: {recall_passed} | Complete: {is_complete} | Contradict: {has_contradiction}")
        
    console.print("\n")
    console.print(table)
    
    # Save results to disk
    output_report_path = os.path.join(
        os.path.dirname(DATASET_PATH), "accuracy_results.json"
    )
    with open(output_report_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)
    console.print(f"\n[bold green]Accuracy report written to {output_report_path}[/bold green]")

if __name__ == "__main__":
    asyncio.run(run_accuracy_benchmark())
