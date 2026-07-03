# Next.js Frontend Integration Guide

This guide describes how to connect a Next.js frontend to our FastAPI backend, consume Server-Sent Events (SSE) streams, manage message states, and render the agent's reasoning steps and final citations in a premium UI.

---

## 1. Local Development Setup

When running Next.js locally (`localhost:3000`), you can call the backend (`localhost:8000`) directly since CORS is enabled for all hosts.

We recommend adding the backend API URL to your Next.js `.env.local` file:
```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

---

## 2. Consuming the SSE Stream in React

To handle custom EventTypes (`thought`, `tool_call`, `observation`, `final_answer`) from FastAPI, we recommend using standard `fetch` with a `ReadableStream` reader. 

Below is a complete, clean TypeScript integration hook that consumes the stream:

```typescript
import { useState } from 'react';

interface Citation {
  node_id: string;
  title: string;
  page_range: number[];
}

interface StreamStep {
  type: 'thought' | 'tool_call' | 'observation' | 'error';
  content: string;
  meta?: any;
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  steps?: StreamStep[]; // Stores the "Thinking..." steps
  citations?: Citation[];
  key_provisions?: string[];
  latency_ms?: number;
}

export function useLegalChat(threadId: string) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);

  const sendMessage = async (userMessage: string) => {
    setIsStreaming(true);
    
    // Add user message immediately
    const userMsgId = crypto.randomUUID();
    const newUserMsg: ChatMessage = { id: userMsgId, role: 'user', content: userMessage };
    
    // Create assistant placeholder message carrying an empty steps array
    const assistantMsgId = crypto.randomUUID();
    const newAssistantMsg: ChatMessage = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      steps: []
    };
    
    setMessages(prev => [...prev, newUserMsg, newAssistantMsg]);

    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/chats/${threadId}/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMessage })
      });

      if (!response.body) throw new Error("No response body");
      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      
      let stepsAccumulator: StreamStep[] = [];
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        
        // Keep the last incomplete line in the buffer
        buffer = lines.pop() || "";

        for (const line of lines) {
          const cleanLine = line.trim();
          if (!cleanLine.startsWith("data: ")) continue;
          
          const rawData = cleanLine.substring(6);
          if (!rawData) continue;

          try {
            const parsed = JSON.parse(rawData);
            
            // Handle intermediate steps
            if (['thought', 'tool_call', 'observation', 'error'].includes(parsed.type)) {
              if (parsed.type === 'tool_call') {
                stepsAccumulator.push({
                  type: 'tool_call',
                  content: `Calling ${parsed.name} with args: ${JSON.stringify(parsed.args)}`
                });
              } else {
                stepsAccumulator.push({
                  type: parsed.type,
                  content: parsed.content
                });
              }
              
              // Update state with active steps
              setMessages(prev => prev.map(m => 
                m.id === assistantMsgId ? { ...m, steps: [...stepsAccumulator] } : m
              ));
            }
            
            // Handle final structured response
            if (parsed.type === 'final_answer') {
              setMessages(prev => prev.map(m => 
                m.id === assistantMsgId ? {
                  ...m,
                  content: parsed.answer_text,
                  citations: parsed.citations,
                  key_provisions: parsed.key_provisions,
                  latency_ms: parsed.latency_ms
                } : m
              ));
            }
          } catch (e) {
            console.error("Error parsing event line", e);
          }
        }
      }
    } catch (error: any) {
      console.error("Stream failed", error);
      setMessages(prev => prev.map(m => 
        m.id === assistantMsgId ? { ...m, content: `Error: ${error.message}` } : m
      ));
    } finally {
      setIsStreaming(false);
    }
  };

  return { messages, sendMessage, isStreaming };
}
```

---

## 3. UI Design and Layout Best Practices (Wow-Factor UI)

To create a premium UI experience, follow these design suggestions using `shadcn/ui` components:

### 1. Collapsible Reasoning Trace (Accordion)
Display the intermediate "thinking steps" above the assistant's final response inside a collapsible **`Accordion`** or **`Collapsible`** component with a custom spinner. This tells the user exactly what the AI is doing, solving the "waiting lag" problem.

- **UI Label**: *"Thinking Process..."* or *"Reasoning Trace"*
- **Aesthetic**: Dark-mode glassmorphic gray container (`bg-muted/30 border border-border/50 rounded-lg p-3 text-xs font-mono`) containing bullet points with icon badges:
  - `thought` events: 💡 *Thought: [content]* (yellow/orange tone).
  - `tool_call` events: 🔍 *Calling Search Tool: [name]* (cyan tone).
  - `observation` events: 📖 *Retrieved Context Preview* (green tone).

### 2. Markdown Final Response
Use a robust React markdown renderer (e.g. `react-markdown` with `remark-gfm`) to render the `content` of the assistant's message.
- Use `prose prose-sm dark:prose-invert` styling to render clean headers, lists, and tables.

### 3. Interactive Citation Anchors
The agent outputs citations in text using standard bracketed IDs (e.g., `[Source: BNS_S35]`). 
- **Custom Token Replacement**: Use a regex utility to replace `\[Source:\s*([A-Za-z0-9_]+)\]` with a clickable UI badge component.
- **Interaction**: Clicking the badge could open a **Sheet** (drawer) on the right showing the full text of that statutory section, or pop open a **HoverCard** tooltip showing the section summary. This provides instant verification without making the user leave their chat window.

### 4. Footnote References Section
At the bottom of the assistant's message, render a clean references block if `citations` array is present.
- Render cards showing the full names and page ranges of the Acts cited:
  ```json
  [1] BNS_S309: 309. Robbery (Pages 82-83)
  ```

---

## 4. Key Performance UX Checklist
1. **Auto-Scroll Safeguard**: Implement a scroll-to-bottom anchor that automatically scrolls as new thoughts or answer chunks stream in, but disables itself if the user manually scrolls up to read history.
2. **Session Persistence**: Call `GET /api/chats/{thread_id}/history` on chat load. If history is found, populate the React messages array, hiding the intermediate steps (they are not saved in checkpointer state to save space, only the final human/assistant text is saved).
3. **Empty State Prompts**: Offer grid suggestion cards for new threads (e.g., *"What is the difference between BNS and old IPC?"*, *"Check police SOP rules for Zero-FIR"*).
