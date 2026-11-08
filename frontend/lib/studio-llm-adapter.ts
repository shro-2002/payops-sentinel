"use client";

import type { AgAiConversationItem, AgAiEvent, AgAiOutputItem, AgLlmAdapter, AgLlmRequest, AgLlmResponse } from "ag-studio";

// AG Studio's provider boundary. Each turn goes to our backend (POST /api/backend/studio/llm), which holds the
// Anthropic key; this file only converts Studio's conversation to the neutral wire shape and back.

type Block =
  | { type: "text"; text: string }
  | { type: "tool_call"; id: string; name: string; input: unknown }
  | { type: "tool_result"; tool_call_id: string; output: string };

interface WireMessage {
  role: "user" | "assistant";
  content: Block[];
}

interface WireTurn {
  id: string;
  model: string;
  stop_reason: string;
  content: Block[];
  usage?: { input_tokens: number; output_tokens: number };
  error?: { code: string; message: string } | null;
}

function parseArgs(json: string): unknown {
  try {
    return JSON.parse(json || "{}");
  } catch {
    return {};
  }
}

// Consecutive items of the same role merge into one message, so all tool results of a turn travel together.
function toWire(items: AgAiConversationItem[]): { system: string[]; messages: WireMessage[] } {
  const system: string[] = [];
  const messages: WireMessage[] = [];
  const push = (role: WireMessage["role"], block: Block) => {
    const last = messages[messages.length - 1];
    if (last?.role === role) last.content.push(block);
    else messages.push({ role, content: [block] });
  };
  for (const item of items) {
    if (item.type === "message" && item.role === "system") {
      system.push(item.content.map((c) => (c.type === "text" ? c.text : "")).join(""));
    } else if (item.type === "message" && item.role === "user") {
      const text = item.content.map((c) => (c.type === "text" ? c.text : "")).join("");
      if (text) push("user", { type: "text", text });
    } else if (item.type === "message" && item.role === "assistant") {
      const text = item.content.map((c) => (c.type === "refusal" ? c.refusal : c.text)).join("");
      if (text) push("assistant", { type: "text", text });
    } else if (item.type === "function_call") {
      push("assistant", { type: "tool_call", id: item.callId, name: item.name, input: parseArgs(item.arguments) });
    } else if (item.type === "function_call_output") {
      push("user", { type: "tool_result", tool_call_id: item.callId, output: item.output });
    }
    // Reasoning items are not replayed.
  }
  return { system, messages };
}

function wireRequest(request: AgLlmRequest) {
  const { system, messages } = toWire(request.input);
  if (request.responseFormat.type === "json") {
    system.push(`Reply with only a JSON object (no prose, no code fence) matching this JSON Schema:\n${JSON.stringify(request.responseFormat.schema)}`);
  }
  return {
    system: [request.instructions ?? "", ...system].filter(Boolean).join("\n\n"),
    messages,
    tools: (request.tools ?? [])
      .filter((t) => (t.kind ?? "client") !== "provided")
      .map((t) => ({ name: t.name, description: t.description, parameters: t.parameters })),
  };
}

// The console proxy caps bodies at 16 KB; Studio's tool schemas alone exceed that, so the turn travels gzipped.
async function gzipBase64(text: string): Promise<string> {
  const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
  const bytes = new Uint8Array(await new Response(stream).arrayBuffer());
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

async function postTurn(request: AgLlmRequest, signal?: AbortSignal): Promise<WireTurn> {
  const res = await fetch("/api/backend/studio/llm", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ gzip_b64: await gzipBase64(JSON.stringify(wireRequest(request))) }),
    cache: "no-store",
    signal,
  });
  const json = (await res.json().catch(() => null)) as { data?: WireTurn; detail?: { message?: string } } | null;
  if (!res.ok || !json?.data) throw new Error(json?.detail?.message ?? `Assistant request failed (HTTP ${res.status})`);
  return json.data;
}

function toEvents(turn: WireTurn): AgAiEvent[] {
  return turn.content.flatMap((b, i): AgAiEvent[] => {
    if (b.type === "text") {
      const messageId = `${turn.id}_${i}`;
      return [
        { type: "TEXT_MESSAGE_START", messageId, role: "assistant" },
        { type: "TEXT_MESSAGE_CONTENT", messageId, delta: b.text },
        { type: "TEXT_MESSAGE_END", messageId },
      ];
    }
    if (b.type === "tool_call") {
      return [
        { type: "TOOL_CALL_START", toolCallId: b.id, toolCallName: b.name },
        { type: "TOOL_CALL_ARGS", toolCallId: b.id, delta: JSON.stringify(b.input ?? {}) },
        { type: "TOOL_CALL_END", toolCallId: b.id },
      ];
    }
    return [];
  });
}

function toOutput(turn: WireTurn): AgAiOutputItem[] {
  return turn.content.flatMap((b, i): AgAiOutputItem[] => {
    const id = `${turn.id}_${i}`;
    if (b.type === "text") {
      return [{ id, kind: "output", type: "message", role: "assistant", status: "completed", content: [{ type: "text", text: b.text, annotations: [] }] }];
    }
    if (b.type === "tool_call") {
      return [{ id, kind: "output", type: "function_call", callId: b.id, name: b.name, arguments: JSON.stringify(b.input ?? {}), status: "completed" }];
    }
    return [];
  });
}

function toResponse(turn: WireTurn): AgLlmResponse {
  return {
    id: turn.id,
    createdAt: Date.now(),
    output: toOutput(turn),
    status: turn.stop_reason === "max_tokens" ? "incomplete" : "completed",
    incompleteDetails: turn.stop_reason === "max_tokens" ? { reason: "max_output_tokens" } : undefined,
    usage: turn.usage ? { inputTokens: turn.usage.input_tokens, outputTokens: turn.usage.output_tokens } : undefined,
    model: turn.model,
  };
}

export const payopsLlmAdapter: AgLlmAdapter = {
  executeTurn(request, options) {
    const turn = postTurn(request, options?.signal);
    return {
      stream: {
        async *[Symbol.asyncIterator]() {
          yield* toEvents(await turn);
        },
      },
      complete: turn.then(toResponse, (e: Error) => ({
        id: `failed_${Date.now()}`,
        createdAt: Date.now(),
        output: [],
        status: "failed",
        error: { code: "ASSISTANT_REQUEST_FAILED", message: e.message },
      })),
    };
  },
};
