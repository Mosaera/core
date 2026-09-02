import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/** The house "are you sure?" step, for actions that reach outside this machine or can't be undone
 *  from the UI. Deliberately small: a title, the specific consequence as children (name the branch,
 *  the account, the credential — never "this item"), and two buttons.
 *
 *  The body is a slot rather than a string because every worthwhile confirmation is specific: a
 *  generic "This cannot be undone" teaches the operator to click through. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  children,
  confirmLabel,
  busyLabel,
  destructive = true,
  busy = false,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  /** Shown on the confirm button while `busy` (house convention: "Deleting…"). */
  busyLabel?: string;
  destructive?: boolean;
  busy?: boolean;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-label={title} className="max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="px-4 text-[12.5px] leading-relaxed text-muted-foreground">{children}</div>
        <DialogFooter className="flex-row justify-end gap-2">
          <Button size="sm" variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button
            size="sm"
            variant={destructive ? "destructive" : "default"}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? (busyLabel ?? confirmLabel) : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
