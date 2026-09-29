// Locking the page behind a modal surface - the phone's account sheet.
//
// No one technique holds everywhere, so the lock is three:
//
//   1. <html> gets .is-scroll-locked (styles.css): overflow hidden on the
//      root, which stops the wheel, the trackpad, the keyboard and scrollbar
//      dragging on desktop and on current iOS. The width the scrollbar took is
//      handed back as padding, so nothing on the page shifts sideways.
//   2. Non-passive wheel and touchmove listeners cancel any scroll gesture
//      that does not start inside the allowed element. Older iOS Safari
//      ignores overflow on the root, and a drag on the dimmed backdrop would
//      otherwise move the page under it. INSIDE the allowed element a gesture
//      is let through only while that element can still scroll that way, so a
//      scroll that reaches the sheet's end never carries on into the page.
//   3. The scroll position is noted when the lock starts and put back exactly
//      when it ends - instantly, because the page's smooth scrolling is for
//      moving within it. Unless the lock ended because you went to another
//      page: then the new page keeps its own position.
//
// The page is never moved (no position: fixed on the body), so sticky and
// fixed elements - the top bar, the tab bar - stay exactly where they are.
// Locks are counted: two surfaces can hold it and it lifts when both let go.

import { useEffect } from 'react';

let holders = 0;
let saved = null;
let release = null;
const allowed = new Set();

function scrollableFor(target) {
  for (const el of allowed) if (el && target instanceof Node && el.contains(target)) return el;
  return null;
}

// Can `el` scroll further in direction `dy` (positive: towards its end)?
function canScroll(el, dy) {
  const max = el.scrollHeight - el.clientHeight;
  if (max <= 0) return false;
  if (dy < 0) return el.scrollTop > 0;
  if (dy > 0) return el.scrollTop < max - 1;
  return true;
}

function engage() {
  const root = document.documentElement;
  saved = {
    x: window.scrollX, y: window.scrollY, path: window.location.pathname,
    padding: root.style.paddingRight,
  };
  const gap = window.innerWidth - root.clientWidth;
  if (gap > 0) root.style.paddingRight = `${gap}px`;
  root.classList.add('is-scroll-locked');

  let lastY = null;
  const onWheel = (event) => {
    const el = scrollableFor(event.target);
    if (!el || !canScroll(el, event.deltaY)) event.preventDefault();
  };
  const onTouchStart = (event) => { lastY = event.touches[0]?.clientY ?? null; };
  const onTouchMove = (event) => {
    const y = event.touches[0]?.clientY ?? null;
    const dy = lastY === null || y === null ? 0 : lastY - y;
    lastY = y;
    const el = scrollableFor(event.target);
    if ((!el || !canScroll(el, dy)) && event.cancelable) event.preventDefault();
  };
  document.addEventListener('wheel', onWheel, { passive: false });
  document.addEventListener('touchstart', onTouchStart, { passive: true });
  document.addEventListener('touchmove', onTouchMove, { passive: false });

  return () => {
    document.removeEventListener('wheel', onWheel);
    document.removeEventListener('touchstart', onTouchStart);
    document.removeEventListener('touchmove', onTouchMove);
    root.classList.remove('is-scroll-locked');
    root.style.paddingRight = saved.padding;
    const samePage = window.location.pathname === saved.path;
    if (samePage && (window.scrollY !== saved.y || window.scrollX !== saved.x)) {
      window.scrollTo({ left: saved.x, top: saved.y, behavior: 'instant' });
    }
    saved = null;
  };
}

// Lock the page; `scrollable`, if given, may still scroll. Returns the unlock.
export function lockScroll(scrollable = null) {
  if (scrollable) allowed.add(scrollable);
  holders += 1;
  if (holders === 1) release = engage();
  let done = false;
  return () => {
    if (done) return;
    done = true;
    if (scrollable) allowed.delete(scrollable);
    holders -= 1;
    if (holders === 0 && release) { release(); release = null; }
  };
}

export function isScrollLocked() { return holders > 0; }

// While `active`, the page is locked; `scrollableRef`'s element may scroll.
export function useScrollLock(active, scrollableRef) {
  useEffect(() => {
    if (!active) return undefined;
    return lockScroll(scrollableRef?.current ?? null);
  }, [active, scrollableRef]);
}
