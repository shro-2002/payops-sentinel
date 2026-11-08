import type { ApiError } from "@/lib/api";

export function Loading({ label }: { label: string }) {
  return (
    <div role="status" className="panel p-6 text-sm text-fg-muted">
      Loading {label}…
    </div>
  );
}

export function ErrorState({ error, onRetry, what }: { error: ApiError; onRetry?: () => void; what: string }) {
  const down = error.status === 502 || error.status === 0;
  return (
    <div role="alert" className="panel border-bad/40 p-4 text-sm">
      <p className="font-semibold text-bad">{down ? "Backend unavailable" : `Could not load ${what}`}</p>
      <p className="mt-1 text-fg-muted">
        {down ? "The PayOps API at BACKEND_URL did not respond. Start the backend and retry." : error.message}{" "}
        <span className="font-mono text-xs text-fg-faint">({error.code})</span>
      </p>
      {onRetry && (
        <button type="button" className="btn btn-ghost mt-3" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ text }: { text: string }) {
  return <p className="panel p-4 text-sm text-fg-muted">{text}</p>;
}
