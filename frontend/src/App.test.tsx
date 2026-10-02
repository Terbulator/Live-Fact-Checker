/**
 * Route smoke tests.
 *
 * These assert the things that are easy to break while refactoring and
 * expensive to notice: that each route mounts, and that neither auth page claims
 * something untrue about itself. They do not assert on marketing copy, which is
 * expected to change.
 *
 * The auth pages run against the real `AuthProvider` with no Supabase project
 * configured, which is itself a case worth covering: every route must still
 * mount and stay honest.
 *
 * `App` owns a BrowserRouter, so the path is set through the history API rather
 * than a MemoryRouter wrapper.
 */

import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import App from './App';

function renderAt(path: string) {
  window.history.pushState({}, '', path);
  return render(<App />);
}

describe('App routes', () => {
  beforeAll(() => {
    // jsdom has no layout, so the landing page's hash scrolling is a no-op.
    Element.prototype.scrollIntoView = () => {};
  });

  afterAll(() => {
    window.history.pushState({}, '', '/');
  });

  it('renders the landing hero at /', () => {
    renderAt('/');
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/fact-check anything/i);
    // "Start for Free" appears in the nav, the hero and the closing CTA. Every
    // one of them must lead to the real dashboard.
    const ctas = screen.getAllByRole('link', { name: /start for free/i });
    expect(ctas.length).toBeGreaterThan(0);
    for (const cta of ctas) {
      expect(cta).toHaveAttribute('href', '/dashboard');
    }
  });

  it('renders the live fact-checker at /dashboard', () => {
    renderAt('/dashboard');
    expect(
      screen.getByRole('heading', { level: 1, name: /^live fact-checker$/i }),
    ).toBeInTheDocument();
  });

  it('mounts the login form and does not claim accounts are unavailable', () => {
    renderAt('/login');
    expect(screen.getByRole('heading', { name: /welcome back/i })).toBeInTheDocument();
    // The old page carried this notice. Nothing may reintroduce it.
    expect(screen.queryByText(/accounts are not implemented/i)).not.toBeInTheDocument();
  });

  it('mounts the signup form and does not claim accounts are unavailable', () => {
    renderAt('/signup');
    expect(screen.getByRole('heading', { name: /create your account/i })).toBeInTheDocument();
    expect(screen.queryByText(/accounts are not implemented/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/not available yet/i)).not.toBeInTheDocument();
  });

  it('falls back to the landing page for an unknown path', () => {
    renderAt('/no-such-page');
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/fact-check anything/i);
  });

  it('marks the guest account as a guest rather than as coming soon', () => {
    renderAt('/dashboard');
    // Accounts are real now, so the badge says who you are, not that the
    // feature is missing.
    expect(screen.getAllByText('GUEST').length).toBeGreaterThan(0);
  });
});
