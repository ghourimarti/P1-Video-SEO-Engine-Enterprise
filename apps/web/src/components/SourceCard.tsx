"use client";

import { Source } from "@/lib/types";

interface Props {
  source: Source;
}

export function SourceCard({ source }: Props) {
  return (
    <div
      className={`rounded-lg border p-3 text-sm ${
        source.cited
          ? "border-brand-500/50 bg-brand-500/10"
          : "border-gray-700 bg-gray-800/50"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="font-semibold text-gray-100 leading-tight">
          {source.name}
        </span>
        {source.score != null && (
          <span className="shrink-0 text-xs text-yellow-400 font-mono">
            ★ {source.score.toFixed(1)}
          </span>
        )}
      </div>
      {source.genres.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {source.genres.map((g) => (
            <span
              key={g}
              className="rounded bg-gray-700 px-1.5 py-0.5 text-xs text-gray-300"
            >
              {g}
            </span>
          ))}
        </div>
      )}
      {source.relevance_score != null && (
        <div className="mt-1.5 text-xs text-gray-500">
          relevance {(source.relevance_score * 100).toFixed(0)}%
        </div>
      )}
    </div>
  );
}
