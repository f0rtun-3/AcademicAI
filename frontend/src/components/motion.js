// Motion helpers: the JavaScript half of the motion system in styles.css §31.
//
// CSS can animate something IN when it mounts, but React removes an element
// the instant its condition turns false, so nothing can animate OUT on its
// own. usePresence keeps a closing element mounted for exactly the length of
// its exit animation, marked `data-state="closed"`, then lets it go.
//
// Reduced motion skips the exit entirely: the element leaves at once, which
// is what "remove decorative movement" means for something closing. So does
// an environment that cannot report the preference at all (no matchMedia) -
// if we cannot tell, the safe answer is not to animate.

import { useEffect, useRef, useState } from 'react';

// In step with the CSS tokens: --dur-fast for popovers and dialogs, --dur for
// toasts. If those tokens change, these must change with them.
export const EXIT_FAST_MS = 140;
export const EXIT_MS = 200;

export function motionAllowed() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
  return !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

// usePresence(when) -> [value, leaving]
//
//   when truthy   [when, false]              shown, open
//   just closed   [last value, true]         still shown, animating out
//   after exit    [null, false]              gone
//
// `value` is the last truthy value while leaving, so a dialog that renders
// from an object ("Cancel COS202 Quiz?") keeps its words as it fades rather
// than rendering with nothing. The SAME element stays mounted from open,
// through the exit, until it is removed - it is never remounted mid-exit.
export function usePresence(when, ms = EXIT_FAST_MS) {
  const last = useRef(when || null);
  const [, rerender] = useState(0);
  if (when) last.current = when;

  useEffect(() => {
    if (when || !last.current) return undefined;
    if (!motionAllowed()) {
      last.current = null;
      return undefined;
    }
    const timer = setTimeout(() => {
      last.current = null;
      rerender((n) => n + 1);
    }, ms);
    return () => clearTimeout(timer);
  }, [when, ms]);

  if (when) return [when, false];
  if (last.current && motionAllowed()) return [last.current, true];
  return [null, false];
}

// useFlash() -> [on, flash]
//
// A short-lived "it worked" state for a control: flash() turns it on, and it
// turns itself off after `ms`. The control's label never changes with it -
// the state only adds a check (styles.css .tick) - so its accessible name,
// and anything that looks it up by name, stays the same.
export function useFlash(ms = 1600) {
  const [on, setOn] = useState(false);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  function flash() {
    clearTimeout(timer.current);
    setOn(true);
    timer.current = setTimeout(() => setOn(false), ms);
  }
  return [on, flash];
}
