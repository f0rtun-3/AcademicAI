import { render } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';
import { AuthProvider } from '../src/auth/AuthContext.jsx';
import { setToken } from '../src/api/client.js';

// Routes the app under test calls, mapped to canned responses. Anything not
// listed answers 404, which surfaces unexpected calls instead of hiding them.
// A request body is either JSON, a FormData (file upload), or absent.
function decodeBody(body) {
  if (!body) return null;
  if (typeof FormData !== 'undefined' && body instanceof FormData) {
    return Object.fromEntries(body.entries());
  }
  try {
    return JSON.parse(body);
  } catch {
    return body;
  }
}

export function mockApi(routes) {
  const calls = [];
  global.fetch = vi.fn(async (url, options = {}) => {
    const path = String(url).replace(/^.*\/api/, '');
    const method = options.method || 'GET';
    calls.push({ path, method, body: decodeBody(options.body) });
    const handler = routes[`${method} ${path}`] ?? routes[path];
    if (!handler) {
      return new Response(JSON.stringify({ error: 'not_found', message: 'Not found.' }),
        { status: 404, headers: { 'Content-Type': 'application/json' } });
    }
    const result = typeof handler === 'function' ? await handler() : handler;
    const status = result?.__status ?? 200;
    return new Response(JSON.stringify(result), {
      status, headers: { 'Content-Type': 'application/json' },
    });
  });
  return calls;
}

export function renderWithAuth(ui, { route = '/', token = 'test-token' } = {}) {
  setToken(token);
  return render(
    <MemoryRouter initialEntries={[route]}
                  future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AuthProvider>{ui}</AuthProvider>
    </MemoryRouter>,
  );
}

// Renders a single route with its params bound, for screens addressed by URL
// (S7 is a route so an event is linkable and survives a refresh).
export function renderAtRoute(path, element, options = {}) {
  return renderWithAuth(
    <Routes><Route path={path} element={element} /></Routes>,
    { route: options.route ?? path, ...options },
  );
}

export const REP_SESSION = {
  user: {
    id: 1, full_name: 'Ada Rep', email: 'ada@babcock.edu.ng', email_verified: true,
    department: 'Software Engineering', level: '200',
    academic_session: '2026/2027',
  },
  membership: { community_id: 1, status: 'ACTIVE', role: 'VERIFIED_REP' },
  pending_membership: null,
  next_step: 'dashboard',
  // As /api/auth/me reports it: the university's academic clock.
  timezone: 'Africa/Lagos',
};

export const STUDENT_SESSION = {
  ...REP_SESSION,
  user: { ...REP_SESSION.user, id: 2, full_name: 'Bola Student' },
  membership: { community_id: 1, status: 'ACTIVE', role: 'STUDENT' },
};

export const COMMUNITY = {
  id: 1, university: 'Babcock University', department: 'Software Engineering',
  level: '200', academic_session: '2026/2027', status: 'ACTIVE',
  member_count: 4, reps: [{ id: 1, full_name: 'Ada Rep', rep_since: '2026-09-15' }],
};
