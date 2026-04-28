export interface Source {
  mal_id: number;
  name: string;
  score: number | null;
  genres: string[];
  relevance_score: number | null;
  cited: boolean;
}

// SSE event types emitted by /api/v1/recommend/stream
export type StepEvent = {
  type: "step";
  step: string;
  trace_id: string;
};

export type TokenEvent = {
  type: "token";
  content: string;
  trace_id: string;
};

export type DoneEvent = {
  type: "done";
  sources: Source[];
  model_used: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  cached: boolean;
  trace_id: string;
};

export type ErrorEvent = {
  type: "error";
  message: string;
  trace_id: string;
};

export type StreamEvent = StepEvent | TokenEvent | DoneEvent | ErrorEvent;

// Assembled message shown in the UI
export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  model_used?: string;
  cost_usd?: number;
  cached?: boolean;
  currentStep?: string;   // shown while streaming
  streaming?: boolean;
}
