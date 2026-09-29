import { useCallback, useEffect, useState } from 'react';

// Small loader hook so every screen gets consistent loading/error/data states
// without repeating the same effect in each page.
export function useResource(loader, deps = []) {
  const [state, setState] = useState({ status: 'loading', data: null, error: null });

  const run = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading' }));
    try {
      const data = await loader();
      setState({ status: 'ready', data, error: null });
    } catch (err) {
      setState({ status: 'error', data: null, error: err });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => { run(); }, [run]);

  // Re-read in place: the page keeps showing what it has, then swaps in the
  // new data - no loading screen, and a failed refresh changes nothing. For
  // updates the reader did not ask for (a reminder firing), where a flash of
  // "Loading…" would be worse than a moment of old data.
  const refresh = useCallback(async () => {
    try {
      const data = await loader();
      setState({ status: 'ready', data, error: null });
    } catch {
      /* keep what is on screen */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { ...state, reload: run, refresh };
}
