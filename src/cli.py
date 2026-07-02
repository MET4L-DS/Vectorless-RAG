import asyncio
import os
from collections import deque
from colorama import init, Fore, Style

from src import retriever
from src import generator

init(autoreset=True)

async def main():
    print(f"{Fore.CYAN}==================================================")
    print(f"{Fore.CYAN}  Vectorless-RAG Legal Conversational Assistant  ")
    print(f"{Fore.CYAN}=================================================={Style.RESET_ALL}\n")
    
    print(f"{Fore.YELLOW}Loading indices...{Style.RESET_ALL}")
    retriever.load("tree")
    
    print(f"\n{Fore.GREEN}Ready!{Style.RESET_ALL} Type your legal query below.")
    print("Commands:")
    print("  'exit'/'quit' - Close assistant")
    print("  'clear'       - Clear chat memory & cached context")
    print("  'debug'       - Toggle retrieval debug trace logs\n")
    
    # Configure conversation history window (Configurable turn count)
    MEMORY_LIMIT = 5
    history = deque(maxlen=MEMORY_LIMIT)
    last_retrieval = None
    debug_mode = False
    
    while True:
        try:
            query = input(f"{Fore.CYAN}Query > {Style.RESET_ALL}")
            if query.strip().lower() in ['exit', 'quit', 'q']:
                break
            if query.strip().lower() == 'clear':
                history.clear()
                last_retrieval = None
                print(f"{Fore.GREEN}Memory and retrieved context cleared!{Style.RESET_ALL}\n")
                continue
            if query.strip().lower() == 'debug':
                debug_mode = not debug_mode
                status = "ENABLED" if debug_mode else "DISABLED"
                print(f"{Fore.YELLOW}Debug traces {status}.{Style.RESET_ALL}\n")
                continue
                
            if not query.strip():
                continue
                
            print(f"\n{Fore.YELLOW}Processing...{Style.RESET_ALL}")
            
            # Call stateful Generation & Verifier Graph
            res = await generator.generate(
                query=query,
                history=list(history),
                last_retrieval=last_retrieval
            )
            
            # Save retrieval result in cache
            last_retrieval = res.get("retrieval")
            
            # 1. Print Confidence Badge
            conf = res.get("confidence", 0.0)
            if conf >= 0.90:
                badge = f"{Fore.GREEN}✓ HIGH CONFIDENCE ({conf:.2f})"
            elif conf >= 0.70:
                badge = f"{Fore.YELLOW}⚠ MEDIUM CONFIDENCE ({conf:.2f})"
            else:
                badge = f"{Fore.RED}✗ LOW CONFIDENCE ({conf:.2f})"
                
            print(f"Status: {badge}{Style.RESET_ALL}")
            print(f"Latency: {res.get('latency_ms', 0)} ms\n")
            
            # 2. Print Answer
            print(f"{Fore.GREEN}--- ANSWER ---{Style.RESET_ALL}")
            print(f"{Fore.WHITE}{res.get('answer', '')}{Style.RESET_ALL}\n")
            
            # 3. Print citations & references if in debug mode or if available
            if debug_mode and last_retrieval:
                meta = last_retrieval.get("query_metadata", {})
                print(f"{Fore.MAGENTA}--- RETRIEVAL DEBUG INFO ---{Style.RESET_ALL}")
                print(f"Target Corpora: {meta.get('target_corpora', [])}")
                print(f"BM25 Hits:      {meta.get('bm25_hits', 0)}")
                print(f"Tree Hits:      {meta.get('tree_hits', 0)}")
                print(f"Cross Ref Hits: {meta.get('cross_ref_enrichment_count', meta.get('cross_ref_hits', 0))}")
                print(f"Unique nodes matched: {meta.get('total_unique_hits', 0)}")
                print()
                
            # Add turn to rolling history
            history.append({
                "user": query,
                "assistant": res.get("answer", "")
            })
            
            print("="*50 + "\n")
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\n{Fore.RED}Error: {e}{Style.RESET_ALL}\n")

if __name__ == "__main__":
    asyncio.run(main())
