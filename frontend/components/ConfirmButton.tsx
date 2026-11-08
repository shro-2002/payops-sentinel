"use client";

import { useId, useRef, type ReactNode } from "react";

interface Props {
  label: string;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  disabled?: boolean;
  variant?: "primary" | "danger" | "ghost";
  testId?: string;
}

// Native <dialog>: focus trap, Escape-to-close and focus restore come from the browser.
export function ConfirmButton({ label, title, body, confirmLabel, onConfirm, disabled, variant = "ghost", testId }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  return (
    <>
      <button type="button" className={`btn btn-${variant}`} disabled={disabled} onClick={() => ref.current?.showModal()} data-testid={testId}>
        {label}
      </button>
      <dialog ref={ref} aria-labelledby={titleId} className="w-[min(92vw,520px)] rounded-lg border border-line bg-ink-850 p-0 text-fg backdrop:bg-black/60">
        <form method="dialog" className="p-5">
          <h2 id={titleId} className="text-base font-semibold">
            {title}
          </h2>
          <div className="mt-3 text-sm text-fg-muted">{body}</div>
          <div className="mt-5 flex justify-end gap-2">
            <button type="submit" value="cancel" className="btn btn-ghost" autoFocus>
              Cancel
            </button>
            <button type="submit" value="ok" className={`btn btn-${variant === "ghost" ? "primary" : variant}`} onClick={onConfirm}>
              {confirmLabel}
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}
