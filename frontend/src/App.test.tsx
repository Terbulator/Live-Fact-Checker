/**
 * Route smoke tests.
 *
 * These assert the things that are easy to break while refactoring and
 * expensive to notice: that each route mounts, and that the auth pages say
 * plainly that no authentication exists. They do not assert on marketing copy,
 * which is expected to change.
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
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/know what's true/i);
    expect(screen.getByRole('link', { name: /start a live check/i })).toBeInTheDocument();
  });

  it('renders the live fact-checker at /dashboard', () => {
    renderAt('/dashboard');
    expect(
      screen.getByRole('heading', { level: 1, name: /^live fact-checker$/i }),
    ).toBeInTheDocument();
  });

  it('does not claim authentication works', () => {
    renderAt('/login');
    expect(screen.getByText(/accounts are not implemented/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^sign in$/i })).toBeDisabled();
  });

  it('marks session history as coming soon rather than built', () => {
    renderAt('/dashboard');
    expect(screen.getAllByText('COMING SOON').length).toBeGreaterThan(0);
  });
});
