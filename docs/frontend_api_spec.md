# Vectorless-RAG Backend API Specification

This document provides the API endpoints, request payloads, response schemas, and Server-Sent Events (SSE) stream structures exposed by the FastAPI backend to build the frontend.

---

## Base Configuration
- **Local URL**: `http://127.0.0.1:8000`
- **CORS**: Configured to allow all origins (`*`) and standard headers (`Authorization`, `Content-Type`).

---

## Endpoints

### 1. Health Status
Verify that the backend service and index structures are loaded.

- **Method**: `GET`
- **Path**: `/`
- **Response**:
  ```json
  {
    "status": "online",
    "message": "Vectorless-RAG Legal Assistant API is fully operational locally."
  }
  ```

---

### 2. Stream Chat Message (Server-Sent Events)
Sends a user message to the ReAct agent and streams the agent's internal thoughts, tool calls, tool outputs, and the final cited response.

- **Method**: `POST`
- **Path**: `/api/chats/{thread_id}/message`
- **URL Parameters**:
  - `thread_id` (string, required): A unique conversation identifier (e.g., UUID or custom slug). Memory checkpoints are keyed by this ID.
- **Request Body**:
  - `Content-Type`: `application/json`
  - Body:
    ```json
    {
      "message": "What is the punishment for robbery?"
    }
    ```
- **Response**:
  - `Content-Type`: `text/event-stream`
  - `Cache-Control`: `no-cache`
  - `Connection`: `keep-alive`

#### SSE Stream Events Structure
Each event is emitted in the standard format `data: <JSON_STRING>\n\n`.
The `data` object always contains a `type` key telling the frontend how to render it.

##### Event A: Agent Thought
Fires when the agent is reasoning about its next step.
```http
data: {"type": "thought", "content": "Under the Bharatiya Nyaya Sanhita (BNS), I need to find the specific section for robbery. I will call search_statutes."}
```

##### Event B: Tool Call
Fires when the agent decides to execute one of the legal search tools.
```http
data: {"type": "tool_call", "name": "search_statutes", "args": {"query": "robbery punishment", "statute_code": "BNS"}}
```

##### Event C: Observation (Tool Output)
Fires when the tool completes, returning the raw observation context (truncated to keep payload lightweight).
```http
data: {"type": "observation", "content": "BNS_S309: Robbery. Whoever commits robbery shall be punished with rigorous imprisonment for a term which may extend to ten years..."}
```

##### Event D: Final Answer
Fires once the agent finishes reasoning and outputs the final structured markdown answer. This is the last event of the stream.
```http
data: {
  "type": "final_answer",
  "answer_text": "Under the Bharatiya Nyaya Sanhita (BNS), robbery is punishable with rigorous imprisonment up to ten years...",
  "key_provisions": [
    "- General robbery: Rigorous imprisonment up to 10 years [Source: BNS_S309].",
    "- Highway robbery (sunset to sunrise): Imprisonment up to 14 years [Source: BNS_S309]."
  ],
  "citations": [
    {
      "node_id": "BNS_S309",
      "title": "309. Robbery",
      "page_range": [82, 83]
    }
  ],
  "is_insufficient_context": false,
  "confidence": 1.0,
  "latency_ms": 8450
}
```

##### Event E: Error
Fires if any exception occurs during agent graph execution.
```http
data: {"type": "error", "content": "API streaming error: Rate limit exceeded."}
```

---

### 3. Retrieve Chat History
Loads the saved message history for a specific thread from the backend checkpointer.

- **Method**: `GET`
- **Path**: `/api/chats/{thread_id}/history`
- **URL Parameters**:
  - `thread_id` (string, required): The target conversation identifier.
- **Response**:
  - `Content-Type`: `application/json`
  - Body:
    ```json
    {
      "thread_id": "test-thread-123",
      "messages": [
        {
          "role": "user",
          "content": "What is the punishment for robbery?"
        },
        {
          "role": "assistant",
          "content": "Under the Bharatiya Nyaya Sanhita (BNS), robbery is punishable with rigorous imprisonment up to ten years..."
        }
      ]
    }
    ```
