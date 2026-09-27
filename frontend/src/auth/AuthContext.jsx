// Session and onboarding state.
//
// The backend decides which onboarding step the user is on and returns it as
// `next_step`. The client never infers it, so a user is never routed to a
// screen that will answer 403 (spec 9).

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api, onUnauthorized, setToken, getToken } from '../api/client.js';
import { setAcademicTimeZone } from '../lib/academicTime.js';

const AuthContext = createContext(null);

export const STEPS = {
  VERIFY_EMAIL: 'verify_email',
  COMMUNITY_SETUP: 'community_setup',
  AWAITING_APPROVAL: 'awaiting_approval',
  DASHBOARD: 'dashboard',
};

export function AuthProvider({ children }) {
  const [session, setSession] = useState(null);
  const [status, setStatus] = useState(getToken() ? 'loading' : 'anonymous');
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setAcademicTimeZone(null);
      setSession(null);
      setStatus('anonymous');
      return null;
    }
    setStatus((current) => (current === 'ready' ? 'ready' : 'loading'));
    try {
      const data = await api.get('/auth/me');
      // Before the session is stored, so the first screen that renders with it
      // already reads dates and times on the university's clock.
      setAcademicTimeZone(data?.timezone ?? null);
      setSession(data);
      setStatus('ready');
      setError(null);
      return data;
    } catch (err) {
      if (err.status === 401) {
        setAcademicTimeZone(null);
        setSession(null);
        setStatus('anonymous');
      } else {
        setError(err.message);
        setStatus('error');
      }
      return null;
    }
  }, []);

  useEffect(() => {
    refresh();
    return onUnauthorized(() => {
      setAcademicTimeZone(null);
      setSession(null);
      setStatus('anonymous');
    });
  }, [refresh]);

  const login = useCallback(async (email, password) => {
    const data = await api.post('/auth/login', { email, password });
    setToken(data.token);
    return refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout');
    } catch {
      /* logging out locally matters more than the server round-trip */
    }
    setToken(null);
    setAcademicTimeZone(null);
    setSession(null);
    setStatus('anonymous');
  }, []);

  const value = useMemo(() => ({
    session,
    status,
    error,
    user: session?.user ?? null,
    membership: session?.membership ?? null,
    pendingMembership: session?.pending_membership ?? null,
    nextStep: session?.next_step ?? null,
    // The university's IANA zone: the clock every date and time is shown on.
    timeZone: session?.timezone ?? null,
    isRep: session?.membership?.role === 'VERIFIED_REP',
    login,
    logout,
    refresh,
  }), [session, status, error, login, logout, refresh]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside AuthProvider');
  return context;
}
