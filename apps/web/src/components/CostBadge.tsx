"use client";

interface Props {
  costUsd: number;
  modelUsed: string;
  cached: boolean;
}

export function CostBadge({ costUsd, modelUsed, cached }: Props) {
  return (
    <div className="flex items-center gap-2 text-xs text-gray-400">
      {cached && (
        <span className="rounded bg-green-900/40 px-1.5 py-0.5 text-green-400 font-medium">
          cached
        </span>
      )}
      <span className="rounded bg-gray-800 px-1.5 py-0.5 font-mono">
        {modelUsed}
      </span>
      <span className="rounded bg-gray-800 px-1.5 py-0.5 font-mono">
        ${costUsd.toFixed(5)}
      </span>
    </div>
  );
}
