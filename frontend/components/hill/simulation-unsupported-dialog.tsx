"use client";

import { useEffect, useRef } from "react";

export interface SimulationUnsupportedDialogProps {
  open: boolean;
  mountainName: string;
  onClose: () => void;
}

/**
 * Shown when Simulate is pressed on a catalog peak without mapped trails or a runout pack.
 */
export default function SimulationUnsupportedDialog({
  open,
  mountainName,
  onClose,
}: SimulationUnsupportedDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (open && !node.open) {
      node.showModal();
    } else if (!open && node.open) {
      node.close();
    }
  }, [open]);

  return (
    <dialog
      ref={dialog}
      onCancel={onClose}
      onClose={onClose}
      className="fixed inset-0 z-50 m-auto max-w-md rounded-lg border border-border bg-card p-0 text-foreground shadow-xl backdrop:bg-background/80"
    >
      <form method="dialog" className="px-5 py-4">
        <h2 className="text-lg font-semibold tracking-[-0.01em]">Simulation not available</h2>
        <p className="mt-2 text-base text-muted-foreground">
          {mountainName} is not one of our prepared demo peaks yet. Debris-flow runout needs mapped
          trails and a local terrain pack—the same setup as Mount Rainier and the other peaks we
          built packs for.
        </p>
        <p className="mt-2 text-base text-muted-foreground">
          You can still run <span className="text-foreground">Analyze now</span> here: the agents use
          this summit&apos;s location, live weather, and the landslide model.
        </p>
        <button
          type="submit"
          className="mt-4 h-10 w-full rounded-md bg-primary text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          OK
        </button>
      </form>
    </dialog>
  );
}
