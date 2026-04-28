"use client";

import { useCallback, useRef, useState } from "react";
import { useAuth, UserButton } from "@clerk/nextjs";
import { v4 as uuidv4 } from "uuid";
import { ChatInput } from "@/components/ChatInput";
import { MessageList } from "@/components/MessageList";
import { streamRecommend } from "@/lib/api";
import type { Message, StreamEvent } from "@/lib/types";

export default function ChatPage() {
  const { getToken } = useAuth();
  const [messages, setMessages]   = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  const abortRef                  = useRef<AbortController | null>(null);

  const updateLastMessage = useCallback(
    (updater: (prev: Message) => Message) => {
      setMessages((msgs) => {
        const copy = [...msgs];
        copy[copy.length - 1] = updater(copy[copy.length - 1]);
        return copy;
      });
    },
    [],
  );

  async function handleQuery(query: string) {
    if (streaming) return;

    // Add user bubble
    setMessages((prev) => [
      ...prev,
      { id: uuidv4(), role: "user", content: query },
    ]);

    // Add empty assistant bubble (streaming)
    const assistantId = uuidv4();
    setMessages((prev) => [
      ...prev,
      {
        id: assistantId,
        role: "assistant",
        content: "",
        streaming: true,
        currentStep: "cache_check",
      },
    ]);

    setStreaming(true);
    abortRef.current = new AbortController();

    try {
      const token = await getToken();
      if (!token) throw new Error("Not authenticated");

      await streamRecommend(
        query,
        5,
        token,
        (event: StreamEvent) => {
          if (event.type === "step") {
            updateLastMessage((m) => ({ ...m, currentStep: event.step }));
          } else if (event.type === "token") {
            updateLastMessage((m) => ({ ...m, content: m.content + event.content }));
          } else if (event.type === "done") {
            updateLastMessage((m) => ({
              ...m,
              streaming:    false,
              currentStep:  undefined,
              sources:      event.sources,
              model_used:   event.model_used,
              cost_usd:     event.cost_usd,
              cached:       event.cached,
            }));
          } else if (event.type === "error") {
            updateLastMessage((m) => ({
              ...m,
              streaming:   false,
              currentStep: undefined,
              content:     m.content || `Error: ${event.message}`,
            }));
          }
        },
        abortRef.current.signal,
      );
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") return;
      updateLastMessage((m) => ({
        ...m,
        streaming:   false,
        currentStep: undefined,
        content:     m.content || "Something went wrong. Please try again.",
      }));
    } finally {
      setStreaming(false);
    }
  }

  return (
    <div className="flex h-screen flex-col bg-gray-950 text-gray-100">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-gray-800 px-6 py-3">
        <div className="flex items-center gap-2">
          <span className="text-xl font-bold text-brand-500">Anime RAG</span>
          <span className="rounded bg-gray-800 px-2 py-0.5 text-xs text-gray-400 font-mono">
            v0.5.0
          </span>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>

      {/* Messages */}
      <main className="flex-1 overflow-y-auto px-4 sm:px-8">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-gray-500">
            <p className="text-lg font-medium">What anime should I watch?</p>
            <p className="text-sm">
              Describe your mood, favourite genres, or a show you loved.
            </p>
          </div>
        ) : (
          <MessageList messages={messages} />
        )}
      </main>

      {/* Input */}
      <footer className="border-t border-gray-800 px-4 py-4 sm:px-8">
        <ChatInput onSubmit={handleQuery} disabled={streaming} />
        <p className="mt-2 text-center text-xs text-gray-600">
          Powered by hybrid RAG · pgvector + BM25 + Cohere Rerank · LangGraph
        </p>
      </footer>
    </div>
  );
}
