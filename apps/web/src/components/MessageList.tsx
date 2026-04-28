"use client";

import { useEffect, useRef } from "react";
import { Message } from "@/lib/types";
import { CostBadge } from "./CostBadge";
import { SourceCard } from "./SourceCard";

const STEP_LABELS: Record<string, string> = {
  cache_check: "Checking cache…",
  cache_hit:   "Cache hit — streaming answer…",
  rewriting:   "Rewriting query…",
  retrieving:  "Retrieving anime…",
  grading:     "Grading results…",
  generating:  "Generating recommendations…",
};

interface Props {
  messages: Message[];
}

export function MessageList({ messages }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="flex flex-col gap-6 py-4">
      {messages.map((msg) => (
        <div
          key={msg.id}
          className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
        >
          <div
            className={`max-w-2xl rounded-2xl px-4 py-3 ${
              msg.role === "user"
                ? "bg-brand-600 text-white"
                : "bg-gray-800 text-gray-100"
            }`}
          >
            {/* Step indicator while streaming */}
            {msg.streaming && msg.currentStep && (
              <div className="mb-2 flex items-center gap-2 text-xs text-gray-400">
                <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500" />
                {STEP_LABELS[msg.currentStep] ?? msg.currentStep}
              </div>
            )}

            {/* Message body — preserve markdown line breaks */}
            <div className="whitespace-pre-wrap leading-relaxed">
              {msg.content}
              {msg.streaming && (
                <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-current" />
              )}
            </div>

            {/* Cost + model */}
            {!msg.streaming && msg.model_used && msg.model_used !== "none" && (
              <div className="mt-2">
                <CostBadge
                  costUsd={msg.cost_usd ?? 0}
                  modelUsed={msg.model_used}
                  cached={msg.cached ?? false}
                />
              </div>
            )}

            {/* Sources */}
            {!msg.streaming && msg.sources && msg.sources.length > 0 && (
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {msg.sources.map((s) => (
                  <SourceCard key={s.mal_id} source={s} />
                ))}
              </div>
            )}
          </div>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
