// A progress indicator for multi-step flows.
//
// It is a READING, never a control. Nothing in it is clickable, because the
// step a user is on is decided by the backend (`next_step`) or by local form
// state — offering a click would imply you can skip ahead, and you cannot.
//
// Rendered as an ordered list so assistive technology gets the sequence for
// free, with the current item marked `aria-current="step"`. Completed steps
// carry a tick; the current one is outlined; later ones are numbered.
//
// On a phone only the current step keeps its label (see the stylesheet) so the
// row never wraps into two lines of unreadable text.

import { IconCheck } from './icons.jsx';

export default function StepList({ steps, current }) {
  const index = steps.findIndex((step) => step.id === current);
  if (index < 0) return null;

  return (
    <ol className="steplist" aria-label="Progress">
      {steps.map((step, i) => {
        const state = i < index ? 'done' : i === index ? 'current' : 'todo';
        return (
          <li key={step.id} data-state={state}
              aria-current={state === 'current' ? 'step' : undefined}>
            <span className="steplist__dot" aria-hidden="true">
              {state === 'done' ? <IconCheck size={12} /> : i + 1}
            </span>
            <span className="steplist__label">{step.label}</span>
            {/* The rule is decoration between items, never after the last. */}
            {i < steps.length - 1 && <span className="steplist__rule" aria-hidden="true" />}
          </li>
        );
      })}
    </ol>
  );
}
