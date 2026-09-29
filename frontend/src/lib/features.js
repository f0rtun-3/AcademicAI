// Features that exist in the code but are switched off in the product.
//
// PASSWORD_RESET_AVAILABLE - password reset emails a code to the account's
// address, and AcademicAI has no production email delivery for students yet:
// a reset "sent" from here would never arrive. Until it does, the Forgot
// password page, Settings and Profile explain that it is not available, and
// the API client refuses to send either reset request (api/client.js), so no
// screen can trigger the email by accident.
//
// The backend implementation is intact (auth_routes forgot/reset-password).
// To turn the feature on once delivery is configured: set this to true.
export const PASSWORD_RESET_AVAILABLE = false;

// The API paths that belong to it, blocked while it is off.
export const PASSWORD_RESET_PATHS = new Set(['/auth/forgot-password', '/auth/reset-password']);
