import "@testing-library/jest-dom/vitest";

// jsdom lacks matchMedia + ResizeObserver, which the sidebar (use-mobile hook)
// and Base UI positioning rely on.
if (!window.matchMedia) {
  window.matchMedia = (query: string): MediaQueryList =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}

// jsdom's window.crypto has getRandomValues but no `subtle`; the integrity-checksum
// verifier needs real WebCrypto. Node's implementation is spec-compliant, so tests
// compute genuine sha-256 digests rather than mocking the math away.
if (!globalThis.crypto?.subtle) {
  const { webcrypto } = await import("node:crypto");
  Object.defineProperty(globalThis.crypto, "subtle", {
    value: webcrypto.subtle,
    configurable: true,
  });
}

if (!("ResizeObserver" in globalThis)) {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  (globalThis as Record<string, unknown>).ResizeObserver = ResizeObserverStub;
}
