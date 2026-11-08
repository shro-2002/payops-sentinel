"use client";

import { useEffect, useState } from "react";

import { apiGet } from "./api";

// AG Studio licence key + AI flag. Read server-side (repo-root .env: AG_STUDIO_LICENSE_KEY, STUDIO_AI) by the
// backend and fetched once per page load. AG licence keys are public by design; unset means trial watermark.

export interface StudioConfig {
  licenseKey: string | undefined;
  aiEnabled: boolean;
}

const ENV_KEY = process.env.NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY || undefined;
const AI_FORCED_OFF = process.env.NEXT_PUBLIC_STUDIO_AI === "0";

let cached: Promise<StudioConfig> | null = null;

function load(): Promise<StudioConfig> {
  cached ??= apiGet<{ license_key: string | null; ai_enabled: boolean }>("studio/config").then(
    (c) => ({ licenseKey: c.license_key ?? ENV_KEY, aiEnabled: c.ai_enabled && !AI_FORCED_OFF }),
    () => ({ licenseKey: ENV_KEY, aiEnabled: false }),
  );
  return cached;
}

/** `null` until resolved, so Studio mounts once with its licence and `ai` (an initial-only property) settled. */
export function useStudioConfig(): StudioConfig | null {
  const [config, setConfig] = useState<StudioConfig | null>(null);
  useEffect(() => {
    let live = true;
    load().then((c) => live && setConfig(c));
    return () => {
      live = false;
    };
  }, []);
  return config;
}
