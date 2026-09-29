// The Terms & Conditions currently in force.
//
// TERMS_VERSION is a stable id, not display text. The sign-up form sends it
// with the acceptance and the backend stores it (users.terms_version); the
// backend holds the same id (auth_service.TERMS_VERSION) and refuses an
// acceptance of any other, so an account can only record agreeing to the
// Terms it was shown. A new version of the Terms changes both, and the date.
export const TERMS_VERSION = '2026-09-29';
export const TERMS_EFFECTIVE = 'Tuesday 29 September 2026';
