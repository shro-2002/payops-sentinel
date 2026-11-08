"use client";

import { useCallback, useEffect, useState } from "react";

// Browser-side client. All calls go through the same-origin proxy
// (/api/backend/...), which injects the operator token server-side.

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api/backend/${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ApiError("Console server unreachable", 0, "NETWORK");
  }
  const json = (await res.json().catch(() => null)) as
    | { data?: T; detail?: { code?: string; message?: string } | string }
    | null;
  if (!res.ok) {
    const detail = json?.detail;
    if (Array.isArray(detail)) {
      const first = detail[0] as { msg?: string; loc?: string[] } | undefined;
      throw new ApiError(first ? `${first.loc?.join(".") ?? ""}: ${first.msg ?? "invalid"}` : "Validation failed", res.status, "VALIDATION_ERROR");
    }
    if (typeof detail === "object" && detail) {
      throw new ApiError(detail.message ?? `HTTP ${res.status}`, res.status, detail.code ?? "ERROR");
    }
    throw new ApiError(typeof detail === "string" ? detail : `HTTP ${res.status}`, res.status, "ERROR");
  }
  return json?.data as T;
}

export const apiGet = <T,>(path: string) => request<T>(path);

export const apiPost = <T,>(path: string, body: unknown = {}) =>
  request<T>(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });

export interface Loadable<T> {
  data: T | undefined;
  error: ApiError | undefined;
  loading: boolean;
  reload: () => void;
}

export function useApi<T>(path: string | null): Loadable<T> {
  const [state, setState] = useState<{ data?: T; error?: ApiError; loading: boolean }>({ loading: !!path });
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!path) return;
    let cancelled = false;
    setState((s) => ({ ...s, loading: true }));
    apiGet<T>(path)
      .then((data) => !cancelled && setState({ data, loading: false }))
      .catch((error: ApiError) => !cancelled && setState((s) => ({ data: s.data, error, loading: false })));
    return () => {
      cancelled = true;
    };
  }, [path, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { ...state, reload } as Loadable<T>;
}
