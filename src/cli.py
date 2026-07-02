import asyncio
import os
import json
from colorama import init, Fore, Style

from src import retriever

init(autoreset=True)

async def main():
    print(f"{Fore.CYAN}==================================================")
    print(f"{Fore.CYAN}  Vectorless-RAG Retrieval Debugger CLI  ")
    print(f"{Fore.CYAN}=================================================={Style.RESET_ALL}\n")
    
    print(f"{Fore.YELLOW}Loading indices...{Style.RESET_ALL}")
    retriever.load("tree")
    
    print(f"\n{Fore.GREEN}Ready!{Style.RESET_ALL} Type your legal query below. Type 'exit' to quit.\n")
    
    while True:
        try:
            query = input(f"{Fore.CYAN}Query > {Style.RESET_ALL}")
            if query.strip().lower() in ['exit', 'quit', 'q']:
                break
            if not query.strip():
                continue
                
            print(f"\n{Fore.YELLOW}Retrieving...{Style.RESET_ALL}")
            
            result = await retriever.query(query)
            
            # Print Metadata
            meta = result["query_metadata"]
            print(f"\n{Fore.MAGENTA}--- METADATA ---{Style.RESET_ALL}")
            print(f"Target Corpora: {meta.get('target_corpora', [])}")
            print(f"Total Latency:  {meta.get('total_latency_ms', 0)} ms")
            print(f"BM25 Hits:      {meta.get('bm25_hits', 0)}")
            print(f"Tree Hits:      {meta.get('tree_hits', 0)}")
            print(f"Cross Ref Hits: {meta.get('cross_ref_hits', 0)}")
            
            # Print Primary Hits
            print(f"\n{Fore.GREEN}--- PRIMARY HITS (Top {len(result['primary'])}) ---{Style.RESET_ALL}")
            for idx, hit in enumerate(result['primary']):
                method = hit.get('retrieval_method', 'unknown')
                score = hit.get('score', 0.0)
                print(f"{Fore.GREEN}[{idx+1}]{Style.RESET_ALL} {Fore.CYAN}{hit['node_id']}{Style.RESET_ALL} (Score: {score:.3f} | By: {method})")
                print(f"    {Fore.YELLOW}Title:{Style.RESET_ALL} {hit['title']}")
                print(f"    {Fore.YELLOW}Summary:{Style.RESET_ALL} {hit['summary'][:150]}...")
            
            # Print Supporting Citations
            print(f"\n{Fore.BLUE}--- SUPPORTING CITATIONS ---{Style.RESET_ALL}")
            for citation in result['citations']:
                print(f" - {citation}")
                
            print("\n" + "="*50 + "\n")
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\n{Fore.RED}Error: {e}{Style.RESET_ALL}\n")

if __name__ == "__main__":
    asyncio.run(main())
