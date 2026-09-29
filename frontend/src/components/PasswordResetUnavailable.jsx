// Password reset, while it is switched off (lib/features.js).
//
// One explanation, said the same way wherever reset is offered: the Forgot
// password page, Settings and Profile. It asks for nothing - no email field,
// because nothing would be sent - and reports nothing about any account.
// It is a state of the product, not an error, so it reads as one: a quiet
// record-style block, not a warning.

import { IconShield } from './icons.jsx';

export const RESET_UNAVAILABLE_TITLE = 'Password reset isn’t available yet';
export const RESET_UNAVAILABLE_BODY = 'We’re still setting up secure email delivery for AcademicAI. '
  + 'Password reset will be available once this is ready.';

// What it means for you right now, under the explanation.
export function ResetStatus() {
  return (
    <div className="resetoff">
      <span className="resetoff__icon" aria-hidden="true"><IconShield size={18} /></span>
      <div>
        <p className="resetoff__k">Your password hasn’t changed</p>
        <p className="resetoff__v">You can still sign in with the password you chose when you created your account.</p>
      </div>
    </div>
  );
}

// The inline form, for Settings and Profile: revealed by their "Reset
// password" control, with the same words as the page.
export function ResetUnavailableNote({ id }) {
  return (
    <div className="resetnote" id={id} role="region" aria-label={RESET_UNAVAILABLE_TITLE}>
      <p className="resetnote__title">{RESET_UNAVAILABLE_TITLE}</p>
      <p className="resetnote__body">{RESET_UNAVAILABLE_BODY}</p>
      <ResetStatus />
    </div>
  );
}
