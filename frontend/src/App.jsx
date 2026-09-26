// Routing and the onboarding gate.
//
// `next_step` comes from the backend. The gate redirects to whichever step the
// backend says the user is on, so the app never renders a screen whose API
// calls would be refused (spec 9, 28).

import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import Layout from './components/Layout.jsx';
import { Loading, ErrorState } from './components/States.jsx';
import { STEPS, useAuth } from './auth/AuthContext.jsx';

import Landing from './pages/Landing.jsx';
import SignUp from './pages/SignUp.jsx';
import Login from './pages/Login.jsx';
import ForgotPassword from './pages/ForgotPassword.jsx';
import VerifyEmail from './pages/VerifyEmail.jsx';
import CommunitySetup from './pages/CommunitySetup.jsx';
import AwaitingApprovalPage from './pages/AwaitingApprovalPage.jsx';
import Dashboard from './pages/Dashboard.jsx';
import AddMessage from './pages/AddMessage.jsx';
import CalendarPage from './pages/CalendarPage.jsx';
import EventDetailPage from './pages/EventDetailPage.jsx';
import CommunityPage from './pages/CommunityPage.jsx';
import RepDashboard from './pages/RepDashboard.jsx';
import ChatPage from './pages/ChatPage.jsx';
import RemindersPage from './pages/RemindersPage.jsx';
import ProfilePage from './pages/ProfilePage.jsx';
import SettingsPage from './pages/SettingsPage.jsx';

const STEP_ROUTES = {
  [STEPS.VERIFY_EMAIL]: '/verify-email',
  [STEPS.COMMUNITY_SETUP]: '/community-setup',
  [STEPS.AWAITING_APPROVAL]: '/awaiting-approval',
};

function Gate({ children, allow }) {
  const { status, nextStep, error, refresh } = useAuth();
  const location = useLocation();

  if (status === 'loading') return <Loading label="Checking your session…" />;
  if (status === 'error') {
    return <ErrorState message={error} onRetry={refresh} />;
  }
  if (status === 'anonymous') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (allow !== nextStep) {
    const target = STEP_ROUTES[nextStep] ?? '/dashboard';
    if (target !== location.pathname) return <Navigate to={target} replace />;
  }
  return children;
}

function Protected({ children }) {
  return <Gate allow={STEPS.DASHBOARD}>{children}</Gate>;
}

function AnonymousOnly({ children }) {
  const { status } = useAuth();
  if (status === 'loading') return <Loading label="Checking your session…" />;
  if (status === 'ready') return <Navigate to="/dashboard" replace />;
  return children;
}

// An unknown URL should land somewhere that makes sense for who is asking: an
// anonymous visitor gets the public page, a signed-in user gets the app. It
// deliberately does NOT send anonymous visitors to /login - being bounced
// straight to a form tells someone nothing about what they just opened.
function NotFound() {
  const { status } = useAuth();
  if (status === 'loading') return <Loading label="Checking your session…" />;
  return <Navigate to={status === 'ready' ? '/dashboard' : '/'} replace />;
}

export default function App() {
  return (
    <Routes>
      {/* The public site is the root. It is shown to EVERYONE rather than
          redirecting a signed-in visitor away: the landing page is the link
          people share, and whoever opens it should see the product. The nav
          offers "Open AcademicAI" instead of "Log in" when there is a
          session, so nobody is asked to sign in twice. */}
      <Route path="/" element={<Landing />} />

      <Route path="/login" element={<AnonymousOnly><Login /></AnonymousOnly>} />
      <Route path="/sign-up" element={<AnonymousOnly><SignUp /></AnonymousOnly>} />
      <Route path="/forgot-password"
             element={<AnonymousOnly><ForgotPassword /></AnonymousOnly>} />

      <Route path="/verify-email" element={<Gate allow={STEPS.VERIFY_EMAIL}><VerifyEmail /></Gate>} />
      <Route path="/community-setup" element={<Gate allow={STEPS.COMMUNITY_SETUP}><CommunitySetup /></Gate>} />
      <Route path="/awaiting-approval" element={<Gate allow={STEPS.AWAITING_APPROVAL}><AwaitingApprovalPage /></Gate>} />

      <Route element={<Protected><Layout /></Protected>}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/add-message" element={<AddMessage />} />
        <Route path="/calendar" element={<CalendarPage />} />
        {/* S7 is a route so an event is linkable and survives a refresh. */}
        <Route path="/events/:eventId" element={<EventDetailPage />} />
        {/* Community sections are routes, so each is linkable and survives a
            refresh. Manage is a Community sub-route; the static segment
            outranks `:section`, so /community/manage is never a section. */}
        <Route path="/community" element={<CommunityPage />} />
        <Route path="/community/manage" element={<RepDashboard />} />
        <Route path="/community/:section" element={<CommunityPage />} />
        {/* The old address of Manage, kept so existing links still land. */}
        <Route path="/rep" element={<Navigate to="/community/manage" replace />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/reminders" element={<RemindersPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>

      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
