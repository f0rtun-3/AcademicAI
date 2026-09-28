// Browser checks for the refinement pass, against a mocked API.
//
// What a unit test cannot see: real layout at real widths, the real computed
// focus outline, and the text a student actually reads on screen. Every page
// here is checked at the five widths the audit named, in light and dark.

import { test, expect } from '@playwright/test';
import { installMockApi, REP, STUDENT } from './fixtures/mockApi.js';

const WIDTHS = [360, 390, 834, 1024, 1440];
const THEMES = ['light', 'dark'];

// Internal terms that must never be on a student's screen: stored tokens,
// field names, transitions, versions, raw confidence and ISO dates.
const LEAK = /\b(SCHEDULED|CANCELLED|PUBLISHED|PENDING|PENDING_APPROVAL|ACTIVE|VERIFIED_REP|DEADLINE_MOVED|VENUE_CHANGED|NORMAL|CREATE)\b|→|->|event_type|course_id|\bversion \d|confidence \d|By the system|\d{4}-\d{2}-\d{2}/;

const PAGES = [
  { name: 'dashboard', path: '/dashboard', session: STUDENT, ready: 'Needs attention' },
  { name: 'chat', path: '/chat', session: STUDENT, ready: 'AcademicAI Assistant' },
  { name: 'event', path: '/events/1', session: STUDENT, ready: 'What changed' },
  { name: 'event-cancelled', path: '/events/4', session: STUDENT, ready: 'What changed' },
  { name: 'community', path: '/community', session: STUDENT, ready: 'Recent changes' },
  { name: 'manage', path: '/community/manage', session: REP, ready: 'Awaiting your decision' },
  { name: 'signup', path: '/sign-up', session: null, ready: 'Create your account' },
];

async function open(page, { path, session, ready }, theme = 'light') {
  await page.emulateMedia({ colorScheme: theme });
  await page.clock.setFixedTime(new Date('2026-09-26T10:00:00Z'));
  const api = await installMockApi(page, { session });
  await page.goto(path);
  await expect(page.getByText(ready, { exact: false }).first()).toBeVisible();
  return api;
}

async function horizontalOverflow(page) {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}

for (const theme of THEMES) {
  for (const width of WIDTHS) {
    test.describe(`${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: width < 700 ? 800 : 900 } });

      for (const target of PAGES) {
        test(`${target.name}: no overflow, no internal terms`, async ({ page }, info) => {
          await open(page, target, theme);
          expect(await horizontalOverflow(page)).toBeLessThanOrEqual(0);
          const text = await page.evaluate(() => document.body.innerText);
          expect(text).not.toMatch(LEAK);
          await page.screenshot({ path: info.outputPath(`${target.name}.png`), fullPage: true });
        });
      }
    });
  }
}

// ── Keyboard focus ─────────────────────────────────────────────────────────

function luminance([r, g, b]) {
  const lin = (c) => { const v = c / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

for (const theme of THEMES) {
  test(`primary button focus is a visible 2px offset outline (${theme})`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, { path: '/events/2', session: STUDENT, ready: 'What changed' }, theme);
    const button = page.getByRole('button', { name: 'Add a reminder' });
    // Arrive by keyboard, which is what :focus-visible answers to.
    await button.focus();
    await page.keyboard.press('Shift+Tab');
    await page.keyboard.press('Tab');
    await expect(button).toBeFocused();

    const style = await button.evaluate((el) => {
      const cs = getComputedStyle(el);
      // The colour behind the outline: the nearest ancestor with a background.
      let node = el.parentElement;
      let bg = 'rgba(0, 0, 0, 0)';
      while (node) {
        bg = getComputedStyle(node).backgroundColor;
        if (!/rgba\(0, 0, 0, 0\)|transparent/.test(bg)) break;
        node = node.parentElement;
      }
      return { style: cs.outlineStyle, width: cs.outlineWidth, offset: cs.outlineOffset,
               color: cs.outlineColor, bg };
    });
    expect(style.style).toBe('solid');
    expect(style.width).toBe('2px');
    expect(style.offset).toBe('2px');
    const rgb = (s) => s.match(/\d+(\.\d+)?/g).slice(0, 3).map(Number);
    const [a, b] = [luminance(rgb(style.color)), luminance(rgb(style.bg))];
    const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    expect(ratio).toBeGreaterThanOrEqual(3);
  });
}

// ── Notifications ──────────────────────────────────────────────────────────

test('the bell and a toast read as one plain-language system', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  const api = await open(page, { path: '/dashboard', session: STUDENT, ready: 'Needs attention' });
  api.fresh = true;
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));

  const toast = page.getByRole('region', { name: 'New notifications' });
  await expect(toast.getByText('Discrete Mathematics Test (MTH202)')).toBeVisible();
  await expect(toast.getByText('Changed', { exact: true })).toBeVisible();
  await expect(toast.getByRole('button', { name: 'View event' })).toBeVisible();

  await page.getByRole('button', { name: /^Notifications/ }).click();
  const panel = page.getByRole('dialog', { name: 'Notifications' });
  await expect(panel.getByText('This quiz, planned for Tuesday 29 September, has been cancelled.'))
    .toBeVisible();
  // The kind label says "Reminder"; the subject does not repeat it.
  await expect(panel.getByText('Data Structures Assignment 2 (COS202)')).toBeVisible();
  expect(await panel.innerText()).not.toMatch(/Reminder:|\d{4}-\d{2}-\d{2}/);
  // Unread rows carry a visible dot; the read one keeps its place without one.
  const dots = panel.locator('.bellrow:not(.bellrow--read) .bellrow__dot');
  expect(await dots.count()).toBe(4);
  await expect(dots.first()).toBeVisible();
});

// ── Shell, navigation and layout ───────────────────────────────────────────

test('phones get an Add message entry on Chat; wider screens keep theirs', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await open(page, { path: '/chat', session: STUDENT, ready: 'AcademicAI Assistant' });
  await expect(page.locator('.topbar__chatadd')).toBeVisible();
  await expect(page.locator('.fab')).toHaveCount(0);

  await page.setViewportSize({ width: 1024, height: 900 });
  await expect(page.locator('.topbar__chatadd')).toBeHidden();
  await expect(page.locator('.sidebar').getByRole('link', { name: 'Add message' })).toBeVisible();
});

test('Manage is a Community sub-route with a working sub-navigation', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, { path: '/rep', session: REP, ready: 'Awaiting your decision' });
  await expect(page).toHaveURL(/\/community\/manage$/);
  await expect(page.locator('.sidenav a.active')).toHaveText('Community');
  const nav = page.getByRole('navigation', { name: 'Community sections' });
  await expect(nav.getByRole('link', { name: 'Manage' })).toHaveAttribute('aria-current', 'page');

  await nav.getByRole('link', { name: 'Elections' }).click();
  await expect(page).toHaveURL(/\/community\/elections$/);
  await expect(page.getByRole('heading', { name: 'Elections' })).toBeVisible();
  await expect(page.locator('.sidenav a.active')).toHaveText('Community');
});

test('the top bar fits at tablet widths, where it used to overflow', async ({ page }) => {
  // 640-799px carries the wordmark, four tabs, Add message, the bell and the
  // account control in one bar; it overflowed by up to 150px before the bar
  // tightened and Add message became its glyph at these widths.
  await page.setViewportSize({ width: 1000, height: 800 });
  await open(page, { path: '/dashboard', session: STUDENT, ready: 'Needs attention' });
  for (const width of [640, 700, 768]) {
    await page.setViewportSize({ width, height: 800 });
    expect(await horizontalOverflow(page), `${width}px`).toBeLessThanOrEqual(0);
    await expect(page.getByRole('button', { name: /^Account/ })).toBeInViewport();
    await expect(page.locator('.topbar').getByRole('link', { name: 'Add message' })).toBeVisible();
  }
});

test('a suggested reminder sits in the conversation, clear of the composer', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const api = await open(page, { path: '/chat', session: STUDENT, ready: 'AcademicAI Assistant' });
  api.suggestion = { title: 'Prepare for Programming II Quiz 1',
                     remind_at_local: '2026-09-27T08:00', timezone: 'Africa/Lagos', event_id: 2 };
  const input = page.getByLabel('Your question');
  await input.fill('What is my next deadline?');
  await input.press('Enter');
  const card = page.getByRole('region', { name: 'Suggested reminder' });
  await expect(card).toBeVisible();
  // Inside the log, so it is announced and scrolled to with its answer...
  await expect(page.getByRole('log').getByRole('region', { name: 'Suggested reminder' }))
    .toHaveCount(1);
  // ...and not underneath the sticky composer once the transcript settles.
  await expect.poll(async () => {
    const cardBox = await card.boundingBox();
    const composer = await page.locator('.composer').boundingBox();
    return cardBox.y + cardBox.height <= composer.y + 1;
  }).toBe(true);
});

test('the top bar keeps its height on a short page', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const api = await installMockApi(page, { session: STUDENT });
  api.emptyChat = true;
  await page.clock.setFixedTime(new Date('2026-09-26T10:00:00Z'));
  await page.goto('/chat');
  await expect(page.getByText('How can I help?')).toBeVisible();
  const height = await page.locator('.topbar').evaluate((el) => el.getBoundingClientRect().height);
  expect(height).toBeLessThan(80);
});

test('a failed chat send keeps the question and the focus', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  const api = await open(page, { path: '/chat', session: STUDENT, ready: 'AcademicAI Assistant' });
  api.chatFails = true;
  const input = page.getByLabel('Your question');
  await input.fill('What is my next deadline?');
  await input.press('Enter');
  await expect(page.getByRole('alert')).toContainText('Your question was not sent');
  await expect(input).toHaveValue('What is my next deadline?');
  await expect(input).toBeFocused();
});

test('a sign-up error sits beside its field, which takes focus', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await open(page, { path: '/sign-up', session: null, ready: 'Create your account' });
  await page.getByLabel('Full name').fill('Ada Student');
  await page.getByLabel('Student email').fill('ada@student.babcock.edu.ng');
  await page.getByLabel('Password', { exact: true }).fill('Password123');
  await page.getByLabel('Confirm password').fill('Password124');
  await page.getByLabel('University').selectOption('Babcock University');
  await page.getByLabel('Department').fill('Software Engineering');
  await page.getByLabel('Level').fill('200');
  await page.getByLabel('Academic session').fill('2026/2027');
  await page.getByLabel('Matric Number').fill('21/1234');
  await page.getByRole('button', { name: 'Create account' }).click();

  const confirm = page.getByLabel('Confirm password');
  await expect(confirm).toBeFocused();
  await expect(confirm).toHaveAttribute('aria-invalid', 'true');
  await expect(page.getByText('Passwords do not match.')).toBeInViewport();
});

// ── Reminder times are on the university's clock, whatever the device says ─
//
// Babcock is on Africa/Lagos (the session's `timezone`). The browser's own zone
// is set per test with timezoneId; it must not move any AcademicAI time. The
// wall-clock value goes to the API as remind_at_local and the backend attaches
// the university's zone (DST included), so the page never computes an instant.

async function createDefaultReminder(page, eventPath) {
  const api = await open(page, { path: eventPath, session: STUDENT, ready: 'What changed' });
  await page.getByRole('button', { name: 'Add a reminder' }).click();
  await page.getByRole('button', { name: 'Create reminder' }).click();
  await expect(page.getByText(/Only you can see it/)).toBeVisible();
  return api.requests.find((r) => r.method === 'POST' && r.path === '/api/reminders').body;
}

for (const device of ['Africa/Lagos', 'Europe/London', 'America/New_York']) {
  test.describe(`on a device set to ${device}`, () => {
    test.use({ timezoneId: device });
    test('Event Detail sends Babcock\'s 08:00 the morning before, as a local time', async ({ page }) => {
      const body = await createDefaultReminder(page, '/events/2');   // quiz on 28 September
      expect(body.remind_at_local).toBe('2026-09-27T08:00');
      expect(body.remind_at).toBeUndefined();
      expect(body.event_id).toBe(2);
    });
  });
}

test.describe('London device, Babcock (Lagos) university, after the UK clocks change', () => {
  test.use({ timezoneId: 'Europe/London' });
  test('the default is still Babcock\'s wall-clock 08:00', async ({ page }) => {
    const body = await createDefaultReminder(page, '/events/9');     // due 26 October
    expect(body.remind_at_local).toBe('2026-10-25T08:00');
  });
});

test.describe('a device set to UTC', () => {
  test.use({ timezoneId: 'UTC' });
  for (const theme of THEMES) {
    test(`a reminder at 00:30 Lagos shows on the Lagos day (${theme})`, async ({ page }) => {
      // "Now" is 10:00Z on Saturday 26 September; the reminder is 00:30 on
      // Sunday 27th in Lagos, which is still the 26th in UTC. It must read as
      // tomorrow, 27 Sep, 00:30 - never "Today 26 Sep".
      await page.setViewportSize({ width: 390, height: 800 });
      await open(page, { path: '/reminders', session: STUDENT, ready: 'Check the portal' }, theme);
      const row = page.locator('.brow', { hasText: 'Check the portal after midnight' });
      await expect(row).toContainText('Tomorrow');
      await expect(row).toContainText('27 Sep');
      await expect(row).toContainText('00:30');
      await expect(row).not.toContainText('26 Sep');

      await page.goto('/dashboard');
      const onDashboard = page.locator('.brow', { hasText: 'Check the portal after midnight' });
      await expect(onDashboard).toContainText('27 Sep');
      await expect(onDashboard).toContainText('00:30');
    });
  }

  test('Chat shows a suggestion in Babcock\'s time and accepts it unchanged', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 800 });
    const api = await open(page, { path: '/chat', session: STUDENT, ready: 'AcademicAI Assistant' });
    api.suggestion = { title: 'Prepare for Programming II Quiz 1',
                       remind_at_local: '2026-09-27T08:00', timezone: 'Africa/Lagos', event_id: 2 };
    const input = page.getByLabel('Your question');
    await input.fill('What is my next deadline?');
    await input.press('Enter');
    await expect(page.getByText('Sunday 27 September at 08:00')).toBeVisible();
    await page.getByRole('button', { name: 'Add reminder' }).click();
    await expect(page.getByText('Personal reminder created.')).toBeVisible();
    const body = api.requests.find((r) => r.method === 'POST' && r.path === '/api/reminders').body;
    expect(body).toEqual({ title: 'Prepare for Programming II Quiz 1',
                           remind_at_local: '2026-09-27T08:00', event_id: 2 });
  });
});
