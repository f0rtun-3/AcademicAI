// Light / dark / system, as three explicit states.
//
// The stylesheet already supported all three: tokens are declared on bare
// :root, overridden under `prefers-color-scheme: dark` guarded by
// `:root:not([data-theme="light"])`, and overridden again under
// `:root[data-theme="dark"]`. That means the only thing missing was a control
// to stamp the attribute — this file adds it and changes no colour.
//
// "System" must stay reachable. A two-state toggle traps someone who picked
// dark at night and then wants their device to decide again.
//
// The choice is a display preference, so localStorage is the right home for
// it: per-browser, no account round trip, and losing it is harmless.

import { useEffect, useState } from 'react';
import { IconMonitor, IconMoon, IconSun } from './icons.jsx';

const KEY = 'academicai:theme';
const MODES = [
  { id: 'light', label: 'Light', Icon: IconSun },
  { id: 'dark', label: 'Dark', Icon: IconMoon },
  { id: 'system', label: 'System', Icon: IconMonitor },
];

function read() {
  try {
    const saved = localStorage.getItem(KEY);
    return saved === 'light' || saved === 'dark' ? saved : 'system';
  } catch {
    // Private browsing and blocked site data both throw here. Falling back to
    // "system" is correct: it is what the page renders with no attribute.
    return 'system';
  }
}

function apply(mode) {
  const root = document.documentElement;
  if (mode === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', mode);
}

export function useTheme() {
  const [mode, setMode] = useState(read);

  useEffect(() => {
    apply(mode);
    try {
      if (mode === 'system') localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, mode);
    } catch { /* preference simply does not persist */ }
  }, [mode]);

  return [mode, setMode];
}

export default function ThemeToggle() {
  const [mode, setMode] = useTheme();
  return (
    <div className="themetoggle" role="group" aria-label="Colour theme">
      {MODES.map(({ id, label, Icon }) => (
        <button key={id} type="button" onClick={() => setMode(id)}
                aria-pressed={mode === id} title={label}>
          <Icon size={16} />
          <span className="sr-only">{label}</span>
        </button>
      ))}
    </div>
  );
}
