"use client";

import { useSyncExternalStore } from "react";

import type { Evidence, Investigation, Proposal } from "./types";

// Custom AG Studio widgets render inside Studio's own component tree, so they read
// page data from this tiny external store instead of React context.

export interface WorkspaceSnapshot {
  investigation: Investigation | null;
  proposals: Proposal[];
  openEvidence: (evidence: Evidence) => void;
}

let snapshot: WorkspaceSnapshot = { investigation: null, proposals: [], openEvidence: () => undefined };
const listeners = new Set<() => void>();

export function setWorkspace(next: WorkspaceSnapshot): void {
  snapshot = next;
  listeners.forEach((l) => l());
}

export function getWorkspace(): WorkspaceSnapshot {
  return snapshot;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useWorkspace(): WorkspaceSnapshot {
  return useSyncExternalStore(subscribe, () => snapshot, () => snapshot);
}
