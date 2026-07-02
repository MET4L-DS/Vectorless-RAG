import os
import asyncio
import itertools
from dotenv import load_dotenv
from google import genai

load_dotenv(override=True)

api_key = os.getenv("GOOGLE_API_KEY")
client = None
if api_key:
    client = genai.Client(api_key=api_key)
else:
    print("Warning: GOOGLE_API_KEY is not set in environment.")

# Define our model pool and their specific rate limits (minimum seconds between calls)
# Gemma 4 26B/31B is limited to 15 RPM (4.0s), but we use 6.0s (10 RPM) for safety.
# Gemini 3.1 Flash-Lite is much faster, we can set it to 15 RPM (4.0s) or negligible if local.
# Let's configure them with specific intervals.
MODEL_CONFIGS = {
    "models/gemma-4-26b-a4b-it": 6.0,
    "models/gemma-4-31b-it": 6.0,
    "models/gemini-3.1-flash-lite": 0.5, # Very low delay for flash-lite
}

MODELS = list(MODEL_CONFIGS.keys())
model_next_allowed_time = {m: 0.0 for m in MODELS}
model_locks = {m: asyncio.Lock() for m in MODELS}
model_cycle = itertools.cycle(MODELS)

# Metrics tracking
new_calls_count = 0
model_calls_tracker = {m: 0 for m in MODELS}

async def call_model(prompt: str, json_mode: bool = False) -> str:
    """
    Alternates between models and enforces model-specific rate limits
    using an async leaky bucket slot reservation system.
    """
    global new_calls_count
    model_name = next(model_cycle)
    min_interval = MODEL_CONFIGS[model_name]
    
    async with model_locks[model_name]:
        now = asyncio.get_event_loop().time()
        target_time = max(now, model_next_allowed_time[model_name])
        delay = target_time - now
        model_next_allowed_time[model_name] = target_time + min_interval

    # Wait outside the lock so other tasks can reserve their slots concurrently
    if delay > 0:
        await asyncio.sleep(delay)
        
    if not client:
        raise ValueError("Google GenAI client is not configured (missing GOOGLE_API_KEY).")
    
    config = None
    if json_mode and "gemini" in model_name:
        config = {"response_mime_type": "application/json"}

    # Call SDK in executor thread
    start_time = asyncio.get_event_loop().time()
    response = await asyncio.to_thread(
        lambda: client.models.generate_content(
            model=model_name, 
            contents=prompt,
            config=config
        )
    )
    elapsed = asyncio.get_event_loop().time() - start_time
    print(f"[Call] Model: {model_name} (Response time: {elapsed:.2f}s)")
    
    model_calls_tracker[model_name] += 1
    new_calls_count += 1
    return response.text.strip()

async def call_model_with_retry(prompt: str, retries: int = 5, json_mode: bool = False) -> str:
    """
    Helper with retry and exponential backoff, handling rate limits specifically.
    """
    for attempt in range(retries):
        try:
            return await call_model(prompt, json_mode=json_mode)
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
