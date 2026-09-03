/* Minimal ambient typing for the two node:crypto surfaces the TEST layer uses
   (the jsdom WebCrypto polyfill in setup.ts and the independent sha-256 fixture
   in ledger.test.tsx). The app itself never imports node builtins, so pulling in
   all of @types/node for this would be disproportionate. */
declare module "node:crypto" {
  export const webcrypto: { subtle: SubtleCrypto };
  export function createHash(algorithm: string): {
    update(data: string): { digest(encoding: "hex"): string };
  };
}
