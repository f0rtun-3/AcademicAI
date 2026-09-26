// The shared screen states every page needs (spec 28), in the design system's
// terms: loading, empty, error, unauthorized, awaiting approval, and the two
// dismissible banners.
//
// 18 · Error copy rule, as corrected (C·5):
//   * A BUSINESS-RULE refusal (400/403/404/409/422) renders the backend's
//     message verbatim. The backend is the only authority on which rule was
//     enforced, so paraphrasing it would create a second source of truth.
//   * A TRANSPORT or SYSTEM failure (network, timeout, 429, 5xx) gets UI
//     framing from the fixed vocabulary below, because a raw internal string
//     carries no business meaning. The framing always says whether anything
//     changed.

import { Notice } from './ui.jsx';
import { IconClose } from './icons.jsx';

const BUSINESS_RULE = new Set([400, 403, 404, 409, 422]);

// Fixed vocabulary. Nothing here invents a rule; each line states what is
// known about whether a write landed — and a failed READ cannot have left one
// half-applied, so it never implies that it might have.
const UNSAVED = 'Something went wrong at our end. Your change may not have been saved '
              + '— reload before trying again.';
const UNREACHABLE = 'We couldn’t reach AcademicAI. Check your connection and try again.';

const FRAMED = {
  write: {
    0: UNREACHABLE,
    429: 'Too many attempts. Try again shortly.',
    500: UNSAVED,
    502: UNSAVED,
    503: 'The service is busy. Nothing was changed. Try again.',
    504: UNSAVED,
  },
  read: {
    0: UNREACHABLE,
    429: 'Too many attempts. Try again shortly.',
    500: 'Something went wrong at our end. Nothing was changed.',
    502: 'Something went wrong at our end. Nothing was changed.',
    503: 'The service is busy. Nothing was changed.',
    504: 'Something went wrong at our end. Nothing was changed.',
  },
};

// What the UI guarantees about the write, per status and intent. This is the
// part the framing exists to say; it is never omitted.
const GUARANTEE = {
  write: {
    503: 'Nothing was changed.',
    500: 'Your change may not have been saved — reload before trying again.',
  },
  read: { 503: 'Nothing was changed.', 500: 'Nothing was changed.' },
};

export function errorText(error, intent = 'write') {
  if (!error) return null;
  if (typeof error === 'string') return error;
  const status = error.status;
  // A business-rule refusal is the backend's sentence, verbatim.
  if (status === undefined || BUSINESS_RULE.has(status)) {
    return error.message || 'Something went wrong.';
  }
  // A transport or system failure gets UI framing (C·5). Where the backend
  // wrote a real sentence - "The AI service is temporarily unavailable" - it is
  // KEPT: framing exists to add what the backend cannot know about the user's
  // situation, not to overwrite what it did say.
  const table = FRAMED[intent] ?? FRAMED.write;
  const framed = table[status] ?? table[500];
  if (!error.serverMessage) return framed;
  const guarantees = GUARANTEE[intent] ?? GUARANTEE.write;
  const guarantee = status === 429 || status === 0 ? null
    : (guarantees[status] ?? guarantees[500]);
  return guarantee ? `${error.serverMessage} ${guarantee}` : error.serverMessage;
}

export function Loading({ label = 'Loading…', rows = 3 }) {
  return (
    <div className="stack" role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">{label}</span>
      <div className="board" aria-hidden="true">
        {Array.from({ length: rows }, (_, i) => (
          <div className="brow" key={i}>
            <div className="brow__when"><span className="skel" style={{ width: '5ch' }} /></div>
            <div className="brow__main stack stack--tight">
              <span className="skel" style={{ width: `${70 - i * 8}%`, height: 14 }} />
              <span className="skel" style={{ width: '40%' }} />
            </div>
            <div className="brow__side">
              <span className="skel" style={{ width: 72, height: 20 }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// These three replace a whole page rather than filling a band inside one, so
// they carry `state--page`: their own surface, because a failure message
// floating on the page ground is the flatness this system exists to remove.
export function ErrorState({ title = 'Something went wrong', message, onRetry }) {
  return (
    <div className="state state--page state--error" role="alert">
      <h2>{title}</h2>
      <p>{errorText(message, 'read')}</p>
      {onRetry && (
        <button type="button" className="btn btn--secondary" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

// 18 · An empty state states what would be here, and how it gets here. No
// illustration — deliberately.
//
// `surface` is for the few empty states that are NOT inside a board — the
// chat transcript is the only one — where the shared padding would leave the
// text sitting on the page ground with no container.
export function EmptyState({ title, message, action, surface = false }) {
  return (
    <div className={`state state--empty${surface ? ' state--page' : ''}`}>
      <h2>{title}</h2>
      {message && <p>{message}</p>}
      {action}
    </div>
  );
}

export function Unauthorized({ message = 'You do not have access to this page.', action }) {
  return (
    <div className="state state--page state--unauthorized" role="alert">
      <h2>Not available to you</h2>
      <p>{message}</p>
      {action}
    </div>
  );
}

export function AwaitingApproval({ community }) {
  return (
    <div className="state state--page state--awaiting" role="status">
      <h2>Waiting for approval</h2>
      <p>
        Your request to join
        {community ? ` ${community.department} ${community.level} (${community.academic_session})` : ' your academic community'}
        {' '}has been sent. A verified course rep needs to approve it before you can
        see official academic information.
      </p>
      {/* Was "You will receive an email once a rep responds", which was
          untrue twice over: no email provider is connected, and approving a
          membership does not enqueue a notification either. What DOES happen
          is that the gate opens, so that is what this says. */}
      <p className="t-meta">
        Access opens here as soon as a rep approves it — check back.
      </p>
    </div>
  );
}

export function SuccessBanner({ message, onDismiss }) {
  if (!message) return null;
  return (
    <Notice tone="pos" role="status">
      <div className="row-x" style={{ justifyContent: 'space-between' }}>
        <span>{message}</span>
        {onDismiss && (
          <button type="button" className="btn btn--quiet" onClick={onDismiss}
                  aria-label="Dismiss"><IconClose size={16} /></button>
        )}
      </div>
    </Notice>
  );
}

export function ErrorBanner({ message, onDismiss }) {
  const text = errorText(message);
  if (!text) return null;
  return (
    <Notice tone="crit" role="alert">
      <div className="row-x" style={{ justifyContent: 'space-between' }}>
        <span>{text}</span>
        {onDismiss && (
          <button type="button" className="btn btn--quiet" onClick={onDismiss}
                  aria-label="Dismiss"><IconClose size={16} /></button>
        )}
      </div>
    </Notice>
  );
}
