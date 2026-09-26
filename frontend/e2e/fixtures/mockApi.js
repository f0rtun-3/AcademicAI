// A mocked API for browser checks.
//
// Every /api call is answered here, so these specs run the real frontend in a
// real browser without the Flask backend or a database. The payloads are
// shaped like the backend's, and the student-facing strings (notification
// copy, chat answers) are the ones the backend now writes - see
// backend/academicai/services/notification_copy.py and ai/chat_heuristic.py.

export const TODAY = '2026-09-26';

const community = {
  id: 3, status: 'ACTIVE', university: 'Babcock University', department: 'Computer Science',
  level: '300', academic_session: '2026/2027', member_count: 64,
  reps: [{ id: 2, full_name: 'Tolu Adeyemi', rep_since: '2026-09-10' }],
  election: { can_start_election: true, eligible_members: 64, required_members: 4,
              members_needed: 0 },
};

export const STUDENT = {
  user: { id: 7, full_name: 'Adaeze Okafor', email: 'adaeze.okafor@student.babcock.edu.ng',
          department: 'Computer Science', level: '300', academic_session: '2026/2027',
          email_verified: true, student_id_number: '21/1234' },
  membership: { community_id: 3, role: 'STUDENT', status: 'ACTIVE', user_id: 7 },
  next_step: 'dashboard',
};

export const REP = {
  ...STUDENT,
  user: { ...STUDENT.user, id: 2, full_name: 'Tolu Adeyemi' },
  membership: { community_id: 3, role: 'VERIFIED_REP', status: 'ACTIVE', user_id: 2 },
};

export const events = [
  { id: 1, title: 'Data Structures Assignment 2', event_type: 'ASSIGNMENT', course_code: 'COS202',
    course_id: 12, event_date: '2026-09-26', event_time: '23:59', venue: null,
    status: 'SCHEDULED', priority: 'HIGH', completed: false,
    description: 'Implement a binary search tree with insert, delete and in-order traversal.\nSubmit a single .zip on the portal.',
    original_message: 'DSA assignment 2 is due TODAY 11:59pm. Submit on portal.',
    attachments: [{ id: 1, filename: 'COS202_Assignment2_brief.pdf', byte_size: 482133,
                    content_type: 'application/pdf' }], version: 2 },
  { id: 2, title: 'Programming II Quiz 1', event_type: 'QUIZ', course_code: 'COS204', course_id: 13,
    event_date: '2026-09-28', event_time: '10:00', venue: 'LT2', status: 'SCHEDULED',
    priority: 'NORMAL', completed: false, attachments: [], version: 3 },
  { id: 3, title: 'Discrete Mathematics Test', event_type: 'TEST', course_code: 'MTH202',
    course_id: 14, event_date: '2026-09-30', event_time: '14:00', venue: 'B107',
    status: 'SCHEDULED', priority: 'NORMAL', completed: true, attachments: [], version: 2 },
  { id: 4, title: 'Computer Architecture Quiz', event_type: 'QUIZ', course_code: 'COS208',
    course_id: 15, event_date: '2026-09-29', event_time: '12:00', venue: 'LT1',
    status: 'CANCELLED', priority: 'NORMAL', completed: false, attachments: [], version: 2 },
  { id: 5, title: 'Group Project Proposal', event_type: 'PROJECT', course_code: 'COS210',
    course_id: 16, event_date: '2026-10-02', event_time: null, venue: null, status: 'SCHEDULED',
    priority: 'NORMAL', completed: false, attachments: [], version: 1 },
  // Either side of the UK clocks going back (25 October 2026), for the
  // reminder-instant check in Europe/London.
  { id: 8, title: 'Research Methods Essay', event_type: 'ASSIGNMENT', course_code: 'COS214',
    course_id: 18, event_date: '2026-10-25', event_time: null, venue: null, status: 'SCHEDULED',
    priority: 'NORMAL', completed: false, attachments: [], version: 1 },
  { id: 9, title: 'Operating Systems Lab', event_type: 'ASSIGNMENT', course_code: 'COS216',
    course_id: 19, event_date: '2026-10-26', event_time: null, venue: null, status: 'SCHEDULED',
    priority: 'NORMAL', completed: false, attachments: [], version: 1 },
];

const created1 = {
  id: 17, entity_type: 'academic_event', entity_id: 1, change_type: 'EVENT_CREATED',
  old_value: null,
  new_value: { title: 'Data Structures Assignment 2', event_type: 'ASSIGNMENT',
               event_date: '2026-09-24', event_time: '23:59', venue: null, priority: 'HIGH',
               status: 'SCHEDULED' },
  created_at: '2026-09-22T09:14:00Z', actor_name: 'Tolu Adeyemi',
};
const moved1 = {
  id: 22, entity_type: 'academic_event', entity_id: 1, change_type: 'DEADLINE_CHANGED',
  old_value: { event_date: '2026-09-24' }, new_value: { event_date: '2026-09-26' },
  created_at: '2026-09-23T18:40:00Z', actor_name: 'Tolu Adeyemi',
  subject: { title: 'Data Structures Assignment 2', course_code: 'COS202', event_type: 'ASSIGNMENT' },
};
const changes = [
  { id: 21, entity_type: 'academic_event', entity_id: 4, change_type: 'EVENT_CANCELLED',
    old_value: { status: 'SCHEDULED' }, new_value: { status: 'CANCELLED' },
    created_at: '2026-09-25T15:02:00Z', actor_name: 'Tolu Adeyemi',
    subject: { title: 'Computer Architecture Quiz', course_code: 'COS208', event_type: 'QUIZ' } },
  { id: 20, entity_type: 'academic_event', entity_id: 3, change_type: 'VENUE_CHANGED',
    old_value: { venue: 'B007' }, new_value: { venue: 'B107' },
    created_at: '2026-09-25T10:00:00Z', actor_name: 'Tolu Adeyemi',
    subject: { title: 'Discrete Mathematics Test', course_code: 'MTH202', event_type: 'TEST' } },
  { id: 19, entity_type: 'academic_event', entity_id: 2, change_type: 'DEADLINE_CHANGED',
    old_value: { event_date: '2026-09-27' }, new_value: { event_date: '2026-09-28' },
    created_at: '2026-09-24T12:00:00Z', actor_name: 'Tolu Adeyemi',
    subject: { title: 'Programming II Quiz 1', course_code: 'COS204', event_type: 'QUIZ' } },
  // A classmate's approval: must never reach a student's screen.
  { id: 18, entity_type: 'community_member', entity_id: 55, change_type: 'MEMBERSHIP_APPROVED',
    old_value: { status: 'PENDING_APPROVAL' }, new_value: { status: 'ACTIVE' },
    created_at: '2026-09-24T08:00:00Z', actor_name: 'Tolu Adeyemi', subject: null },
  moved1, created1,
];

const timetable = [
  { id: 1, title: 'Data Structures', course_code: 'COS202', course_id: 12, day_of_week: 'MONDAY',
    start_time: '08:00', venue: 'LT2', status: 'ACTIVE', version: 1 },
  { id: 2, title: 'Programming II', course_code: 'COS204', course_id: 13, day_of_week: 'TUESDAY',
    start_time: '10:00', venue: 'B007', status: 'ACTIVE', version: 1 },
];
const courses = [
  { id: 12, code: 'COS202', title: 'Data Structures and Algorithms', enrolled: true, version: 1 },
  { id: 13, code: 'COS204', title: 'Programming II', enrolled: true, version: 1 },
];
const announcements = [
  { id: 1, title: 'Portal maintenance on Friday',
    body: 'The e-learning portal will be offline from 6pm to 9pm on Friday. Submit early.',
    status: 'PUBLISHED', created_at: '2026-09-25T09:00:00Z', author_name: 'Tolu Adeyemi',
    version: 1 },
];
const reminders = [
  { id: 1, title: 'Prepare for Programming II Quiz 1', remind_at: '2026-09-27T07:00:00Z',
    status: 'PENDING', event_id: 2 },
  { id: 2, title: 'Revise pointers', remind_at: '2026-09-25T17:00:00Z', status: 'SENT',
    event_id: null },
];

// In-app wording exactly as notification_copy.py now writes it.
export const notifications = [
  { id: 103, kind: 'EVENT_CANCELLED', link: '/events/4',
    subject: 'Computer Architecture Quiz (COS208)',
    body: 'This quiz, planned for Tuesday 29 September, has been cancelled.',
    created_at: '2026-09-25T15:02:00Z', read_at: null },
  { id: 102, kind: 'EVENT_REMINDER', link: '/events/1',
    subject: 'Data Structures Assignment 2 (COS202)',
    body: 'Due Saturday 26 September at 23:59.',
    created_at: '2026-09-26T08:00:00Z', read_at: null },
  { id: 101, kind: 'EVENT_CREATED', link: '/events/5', subject: 'Group Project Proposal (COS210)',
    body: 'A new project was added for COS210, due Friday 2 October.',
    created_at: '2026-09-24T09:00:00Z', read_at: null },
  { id: 100, kind: 'PERSONAL_REMINDER', link: '/reminders', subject: 'Revise pointers',
    body: null, created_at: '2026-09-25T17:00:00Z', read_at: '2026-09-25T18:00:00Z' },
];
export const freshNotification = {
  id: 104, kind: 'EVENT_CHANGED', link: '/events/3', subject: 'Discrete Mathematics Test (MTH202)',
  body: 'The venue changed from B007 to B107.', created_at: '2026-09-26T09:59:00Z', read_at: null,
};

// Chat answers as chat_heuristic.py now words them.
const chatMessages = [
  { role: 'user', content: 'What changed recently?' },
  { role: 'assistant', content: 'Here is what changed recently in your community:\n'
    + '- Computer Architecture Quiz (COS208) was cancelled. (25 September)\n'
    + '- The venue for Discrete Mathematics Test (MTH202) changed from B007 to B107. (25 September)\n'
    + '- The deadline for Programming II Quiz 1 (COS204) moved from 27 September to 28 September.' },
  { role: 'user', content: 'What classes do I have tomorrow?' },
  { role: 'assistant', content: "You don't have anything scheduled tomorrow." },
];

function payloadFor(url, state) {
  const { pathname, search } = new URL(url);
  const path = pathname.replace(/^\/api/, '');
  const session = state.session;
  if (path === '/auth/me') return session ? [200, session] : [401, { error: 'unauthorized' }];
  if (path === '/dashboard') {
    return [200, {
      greeting: `Good afternoon, ${session.user.full_name.split(' ')[0]}`, community,
      upcoming: events.filter((e) => e.status === 'SCHEDULED'),
      recent_changes: changes, announcements, reminders,
      rep: session.membership.role === 'VERIFIED_REP'
        ? { student_count: 61, rep_count: 1, course_count: 2, timetable_count: 2,
            pending_requests: [{ user_id: 40, full_name: 'Chidi Eze',
                                 requested_at: '2026-09-25T11:00:00Z' }] }
        : null,
    }];
  }
  if (path === '/calendar') return [200, { events, timetable }];
  if (path === '/notifications') {
    state.notificationCalls += 1;
    const list = state.fresh && state.notificationCalls > 1
      ? [freshNotification, ...notifications] : notifications;
    return [200, { notifications: list, unread: list.filter((n) => !n.read_at).length }];
  }
  if (path === '/chat/prompts') {
    return [200, { prompts: ['What assignments do I have this week?',
      'What classes do I have tomorrow?', 'What is my next deadline?',
      'What changed recently?'] }];
  }
  if (path === '/chat/history') {
    if (state.emptyChat) return [200, { conversations: [] }];
    return [200, search.includes('conversation_id')
      ? { conversation_id: 1, messages: chatMessages } : { conversations: [{ id: 1 }] }];
  }
  if (path === '/chat') return state.chatFails
    ? [503, { error: 'unavailable', message: 'The AI service is temporarily unavailable.' }]
    : [201, { answer: "You don't have anything scheduled tomorrow.", grounded: true,
             referenced_event_ids: [], suggested_reminder: null, conversation_id: 1 }];
  if (path === '/community') return [200, { community, membership: session.membership }];
  if (path === '/community/courses') return [200, { courses }];
  if (path === '/community/timetable') return [200, { timetable }];
  if (path === '/community/announcements') return [200, { announcements }];
  if (path.startsWith('/community/changes')) return [200, { changes }];
  if (path === '/community/calendar') return [200, { calendar: null }];
  if (path === '/reminders') {
    if (state.lastRequest?.method === 'POST') {
      return [201, { reminder: { id: 9, status: 'PENDING', event_id: 1,
                                 ...state.lastRequest.body } }];
    }
    return [200, { reminders }];
  }
  if (path === '/rep/candidates') return [200, { candidates: [] }];
  if (path === '/rep/removals') return [200, { removals: [] }];
  if (path === '/universities') {
    return [200, { universities: [{ id: 1, name: 'Babcock University',
      domains: [{ domain: 'student.babcock.edu.ng', domain_type: 'STUDENT' }] }] }];
  }
  const match = path.match(/^\/events\/(\d+)$/);
  if (match) {
    const id = Number(match[1]);
    const history = id === 1 ? [created1, moved1]
      : id === 4 ? [{ ...created1, id: 30, entity_id: 4, new_value: {
        title: 'Computer Architecture Quiz', event_type: 'QUIZ', event_date: '2026-09-29',
        event_time: '12:00', venue: 'LT1', priority: 'NORMAL', status: 'SCHEDULED' } }, changes[0]]
        : [];
    return [200, { event: events.find((e) => e.id === id), history }];
  }
  return [200, {}];
}

/**
 * Answer every /api request for `page` from the fixtures above.
 * Returns a state object: flip `fresh`, `chatFails` or `emptyChat` to change
 * what later requests see, and read `requests` to inspect what was sent.
 */
export async function installMockApi(page, { session = STUDENT } = {}) {
  const state = {
    session, fresh: false, chatFails: false, emptyChat: false,
    notificationCalls: 0, requests: [], lastRequest: null,
  };
  if (session) {
    await page.addInitScript(() => localStorage.setItem('academicai.token', 'e2e'));
  }
  // Only real API paths: `/src/api/client.js` is a module the dev server
  // serves, not an API call.
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => {
    const request = route.request();
    let body = null;
    try { body = request.postDataJSON(); } catch { body = null; }
    state.lastRequest = { method: request.method(), path: new URL(request.url()).pathname, body };
    state.requests.push(state.lastRequest);
    const [status, payload] = payloadFor(request.url(), state);
    return route.fulfill({ status, contentType: 'application/json',
                           body: JSON.stringify(payload) });
  });
  return state;
}
