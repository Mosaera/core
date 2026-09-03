import { useState } from "react";

import { computeReceiptChecksum, type LedgerRow } from "../../lib/ledger";

type SealRow = Extract<LedgerRow, { kind: "seal" }>;

type VerifyState =
  | { state: "idle" }
  | { state: "checking" }
  | { state: "match" }
  | { state: "mismatch" }
  | { state: "uncomputable" };

/** The checksum verifier: recompute the sha-256 in THIS browser from the facts
 *  on the page and compare against the sealed fingerprint. Every outcome is
 *  reported honestly; outside a secure context the button explains itself. */
export function ChecksumVerify({ row }: { row: SealRow }) {
  const [verify, setVerify] = useState<VerifyState>({ state: "idle" });
  const canTry = typeof crypto !== "undefined" && Boolean(crypto.subtle);

  async function runVerify() {
    setVerify({ state: "checking" });
    const computed = await computeReceiptChecksum(row);
    if (computed == null) {
      setVerify({ state: "uncomputable" });
      return;
    }
    setVerify({ state: computed === row.receiptId ? "match" : "mismatch" });
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {canTry ? (
        <button
          onClick={() => void runVerify()}
          disabled={verify.state === "checking"}
          className="w-fit rounded-md border border-border/60 bg-transparent px-3 py-1.5 font-mono text-[12px] text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          {verify.state === "checking" ? "verifying…" : "Verify checksum"}
        </button>
      ) : (
        <p className="font-mono text-[10px] text-muted-foreground/60">
          Verification needs a secure connection (https or localhost).
        </p>
      )}
      {verify.state === "match" && (
        <p role="status" className="font-mono text-[12px] text-success">
          ✓ Verified — the record is intact. The checksum matches what&apos;s on this page.
        </p>
      )}
      {verify.state === "mismatch" && (
        <p role="status" className="font-mono text-[12px] text-destructive">
          ✗ Checksum mismatch — this record does not match its recorded fingerprint.
        </p>
      )}
      {verify.state === "uncomputable" && (
        <p role="status" className="font-mono text-[12px] text-muted-foreground">
          Can&apos;t verify — this record predates the checksum inputs.
        </p>
      )}
    </div>
  );
}
