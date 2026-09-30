// How an account's email stands, in one place, so no screen words it
// differently. The backend decides (auth_service.email_verification_status):
//
//   verified      a code was entered
//   not_required  the account was let through while this deployment had
//                 email verification switched off - nothing was checked, so it
//                 must never read as "verified"
//   pending       not verified yet
//
// `email_verified` alone cannot tell the first two apart: it is true for both.
// It is only the fallback for a session from before `email_verification`.

export const EMAIL_STATUS_LABEL = {
  verified: 'Email verified',
  not_required: 'Email verification not required',
  pending: 'Email not verified',
};

export function emailVerificationStatus(user) {
  if (!user) return null;
  if (user.email_verification in EMAIL_STATUS_LABEL) return user.email_verification;
  return user.email_verified ? 'verified' : 'pending';
}
