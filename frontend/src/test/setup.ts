import '@testing-library/jest-dom';
import { configure } from '@testing-library/react';
import { vi } from 'vitest';

/**
 * How long a `findBy*` waits before giving up.
 *
 * The default is one second, which is fine on a quiet machine and is a coin flip
 * on a busy one: a single slow test-file transform can push a render past a
 * second and turn a passing assertion into a timeout. Five seconds keeps these
 * tests about the code rather than about how busy the machine is, and it cannot
 * hide a real failure — a broken assertion still never arrives.
 */
configure({ asyncUtilTimeout: 5000 });

// Mock matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Mock ResizeObserver
global.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}));

// Mock IntersectionObserver. jsdom does not implement it, and the landing page
// uses `whileInView`, which needs it to mount. Reporting every element as
// intersecting keeps `viewport={{ once: true }}` sections visible in tests
// instead of leaving them at their `initial` opacity.
class MockIntersectionObserver implements IntersectionObserver {
  readonly root: Element | null = null
  readonly rootMargin: string = ''
  readonly thresholds: ReadonlyArray<number> = []

  constructor(private readonly callback: IntersectionObserverCallback) {}

  observe(target: Element): void {
    this.callback(
      [
        {
          isIntersecting: true,
          intersectionRatio: 1,
          target,
          time: 0,
        } as IntersectionObserverEntry,
      ],
      this,
    )
  }

  unobserve(): void {}
  disconnect(): void {}
  takeRecords(): IntersectionObserverEntry[] {
    return []
  }
}

global.IntersectionObserver = MockIntersectionObserver as unknown as typeof IntersectionObserver

// jsdom implements no layout, so scrolling an element into view is not a thing
// it can do. Components that keep the newest line or message in view call it on
// mount; without a stub those components cannot be rendered in a test at all.
if (typeof Element.prototype.scrollIntoView !== 'function') {
  Element.prototype.scrollIntoView = function scrollIntoView() {}
}