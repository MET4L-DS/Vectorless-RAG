import os
import asyncio
import itertools
from typing import Any
from dotenv import load_dotenv
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv(override=True)

api_key = os.getenv("GOOGLE_API_KEY")

# Define our model pool and their specific rate limits (minimum seconds between calls)
MODEL_CONFIGS = {
    # "models/gemma-4-26b-a4b-it": 6.0,
    # "models/gemma-4-31b-it": 6.0,
    "models/gemini-3.1-flash-lite": 0.5, # Enforce 12 RPM pacing (1 request per 5.0s)
}

MODELS = list(MODEL_CONFIGS.keys())
model_next_allowed_time = {m: 0.0 for m in MODELS}
model_locks = {}
model_cycle = itertools.cycle(MODELS)

def get_model_lock(model_name: str) -> asyncio.Lock:
    if model_name not in model_locks:
        model_locks[model_name] = asyncio.Lock()
    return model_locks[model_name]

# Metrics tracking
new_calls_count = 0
model_calls_tracker = {m: 0 for m in MODELS}
call_history = []

def get_langchain_model(model_name: str, temperature: float = 0.0, json_mode: bool = False) -> ChatGoogleGenerativeAI:
    if not api_key:
        raise ValueError("GOOGLE_API_KEY is not set in environment.")
    
    # Pass response_mime_type directly to constructor to prevent UserWarning
    mime_type = "application/json" if json_mode else None

    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        temperature=temperature,
        response_mime_type=mime_type,
        max_retries=10
    )

async def _execute_with_rate_limit(model_name: str, fn, description: str = "Unknown") -> Any:
    """
    Enforces rate limits using the async leaky bucket slot reservation system
    and executes the LangChain invocation.
    """
    global new_calls_count
    min_interval = MODEL_CONFIGS.get(model_name, 1.0)
    
    lock = get_model_lock(model_name)
    async with lock:
        now = asyncio.get_event_loop().time()
        target_time = max(now, model_next_allowed_time.get(model_name, 0.0))
        delay = target_time - now
        model_next_allowed_time[model_name] = target_time + min_interval

    if delay > 0:
        await asyncio.sleep(delay)
        
    start_time = asyncio.get_event_loop().time()
    
    # Run the invoke function (e.g. model ainvoke)
    result = await fn()
    
    elapsed = asyncio.get_event_loop().time() - start_time
    print(f"[Call] Model: {model_name} (Response time: {elapsed:.2f}s)")
    
    call_history.append({
        "model": model_name,
        "elapsed": elapsed,
        "description": description
    })
    
    model_calls_tracker.setdefault(model_name, 0)
    model_calls_tracker[model_name] += 1
    new_calls_count += 1
    return result

async def call_model_with_retry(prompt: str, retries: int = 5, json_mode: bool = False, model_name: str = None) -> str:
    """
    Raw text LLM call with LangChain, wrapped in retry and rate-limiting.
    """
    if not model_name:
        model_name = next(model_cycle)
        
    desc = "Raw Text"
    if "chapters" in prompt.lower():
        desc = "Chapter Selection"
    elif "sections" in prompt.lower():
        desc = "Section Selection"
    elif "sop" in prompt.lower():
        desc = "SOP Selection"

    for attempt in range(retries):
        try:
            llm = get_langchain_model(model_name, json_mode=json_mode)
            # ainvoke returns a BaseMessage, content is the text response
            fn = lambda: llm.ainvoke(prompt)
            response = await _execute_with_rate_limit(model_name, fn, description=desc)
            
            # Handle list content in newer model output wrappers
            content = response.content
            if isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, str):
                        parts.append(part)
                    elif isinstance(part, dict) and "text" in part:
                        parts.append(part["text"])
                    elif hasattr(part, "text"):
                        parts.append(part.text)
                    elif hasattr(part, "get") and part.get("text"):
                        parts.append(part.get("text"))
                content = "".join(parts)
                
            return content.strip()

        except Exception as e:
            err_msg = str(e)
            print(f"Error calling model (attempt {attempt+1}/{retries}): {e}")
            if "429" in err_msg or "Quota" in err_msg or "ResourceExhausted" in err_msg:
                backoff = 35 + (attempt * 15)
                print(f"Rate limit (429) hit. Backing off for {backoff} seconds...")
                await asyncio.sleep(backoff)
            else:
                await asyncio.sleep(2 ** attempt + 5)
            if attempt == retries - 1:
                raise e

async def call_model_structured(prompt: str, response_schema: type[BaseModel], model_name: str = None, retries: int = 5) -> Any:
    """
    Structured schema LLM call with LangChain, wrapped in retry and rate-limiting.
    Returns an instance of response_schema (Pydantic model).
    """
    if not model_name:
        model_name = next(model_cycle)
        
    desc = "Structured Request"
    if "chapters" in prompt.lower():
        desc = "Chapter Selection"
    elif "sections" in prompt.lower():
        desc = "Section Selection"
    elif "sop" in prompt.lower():
        desc = "SOP Selection"

    for attempt in range(retries):
        try:
            llm = get_langchain_model(model_name)
            structured_llm = llm.with_structured_output(response_schema)
            fn = lambda: structured_llm.ainvoke(prompt)
            result = await _execute_with_rate_limit(model_name, fn, description=desc)
            return result
        except Exception as e:
            err_msg = str(e)
            print(f"Error calling model structured (attempt {attempt+1}/{retries}): {e}")
            if "429" in err_msg or "Quota" in err_msg or "ResourceExhausted" in err_msg:
                backoff = 35 + (attempt * 15)
                print(f"Rate limit (429) hit. Backing off for {backoff} seconds...")
                await asyncio.sleep(backoff)
            else:
                await asyncio.sleep(2 ** attempt + 5)
            if attempt == retries - 1:
                raise e

