// Browser checks for the motion system (styles.css §31, components/motion.js).
//
// "Static at rest, alive during interaction": things animate when they open,
// close, arrive or change state - and under reduced motion every change still
// happens, instantly, with nothing lingering on screen.

import { test, expect } from '@playwright/test';
import { installMockApi, STUDENT } from './fixtures/mockApi.js';

async function open(page, path, { width = 1440, reduced = false } = {}) {
  await page.setViewportSize({ width, height: width < 700 ? 800 : 900 });
  await page.emulateMedia({ reducedMotion: reduced ? 'reduce' : 'no-preference' });
  await page.clock.setFixedTime(new Date('2026-09-26T10:00:00Z'));
  const api = await installMockApi(page, { session: STUDENT });
  await page.goto(path);
  return api;
}

const overflow = (page) => page.evaluate(
  () => document.documentElement.scrollWidth - window.innerWidth);

// ── Popovers leave through their closing state ─────────────────────────────

test('the account menu plays its closing state, then is removed', async ({ page }) => {
  await open(page, '/dashboard');
  await expect(page.getByText('Needs attention').first()).toBeVisible();
  await page.getByRole('button', { name: /^Account/ }).click();
  const menu = page.getByRole('menu');
  await expect(menu).toHaveAttribute('data-state', 'open');
  await page.keyboard.press('Escape');
  await expect(menu).toHaveAttribute('data-state', 'closed');
  await expect(menu).toHaveCount(0);
});

test('under reduced motion the menu closes at once, with no closing state', async ({ page }) => {
  await open(page, '/dashboard', { reduced: true });
  await expect(page.getByText('Needs attention').first()).toBeVisible();
  await page.getByRole('button', { name: /^Account/ }).click();
  await expect(page.getByRole('menu')).toBeVisible();
  await page.keyboard.press('Escape');
  // Read in the same task as the key press: nothing is left behind to fade.
  expect(await page.locator('.menu').count()).toBe(0);
});

// ── Toasts, the bell ───────────────────────────────────────────────────────

test('a new notification swings the bell once and a dismissed toast leaves',
  async ({ page }) => {
    const api = await open(page, '/dashboard', { width: 390 });
    await expect(page.getByText('Needs attention').first()).toBeVisible();
    // Loading notifications that already existed does not move the bell.
    await expect(page.locator('.bell__btn--nudge')).toHaveCount(0);

    api.fresh = true;
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await expect(page.locator('.bell__btn--nudge')).toHaveCount(1);
    // ...once: the swing class is removed again, it never loops.
    await expect(page.locator('.bell__btn--nudge')).toHaveCount(0);

    const region = page.getByRole('region', { name: 'New notifications' });
    await expect(region.locator('.toast')).toHaveCount(1);
    await region.getByRole('button', { name: /^Dismiss/ }).click();
    await expect(region.locator('.toast--leaving')).toHaveCount(1);
    await expect(region.locator('.toast')).toHaveCount(0);
  });

// ── Chat ───────────────────────────────────────────────────────────────────

test('an accepted suggestion becomes its own confirmation', async ({ page }) => {
  const api = await open(page, '/chat', { width: 390 });
  await expect(page.getByText('AcademicAI Assistant').first()).toBeVisible();
  api.suggestion = { title: 'Prepare for Programming II Quiz 1',
                     remind_at_local: '2026-09-27T08:00', timezone: 'Africa/Lagos', event_id: 2 };
  const input = page.getByLabel('Your question');
  await input.fill('What is my next deadline?');
  await input.press('Enter');
  // The new answer arrives as a live turn; a restored history does not animate.
  await expect(page.locator('.turn--ai.turn--live')).toHaveCount(1);

  await page.getByRole('button', { name: 'Add reminder' }).click();
  const done = page.getByRole('region', { name: 'Personal reminder created' });
  await expect(done).toBeVisible();
  await expect(done.getByText('Personal reminder created.')).toBeVisible();
  await expect(done.getByText('Sunday 27 September at 08:00')).toBeVisible();
  await expect(done.getByRole('link', { name: 'See your reminders' })).toBeVisible();
  // The pressed button is gone, so the keyboard goes back to the conversation.
  await expect(input).toBeFocused();
});

// ── Entrances never trap a dialog under the page's fixed chrome ────────────
//
// An entrance animation that HOLDS its end state (fill-mode forwards/both)
// keeps a stacking context on the page for good, and a dialog inside it was
// drawn under the phone's tab bar and floating Add message. Entrances fill
// backwards only, so once they have played nothing is left behind.

test('a dialog on a phone sits above the tab bar and the floating button', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.clock.setFixedTime(new Date('2026-09-26T10:00:00Z'));
  const { REP } = await import('./fixtures/mockApi.js');
  await installMockApi(page, { session: REP });
  await page.goto('/events/2');
  await page.getByRole('button', { name: 'Cancel event' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await page.waitForTimeout(400);   // past every entrance
  const covered = await page.evaluate(() => {
    const topAt = (el) => {
      const r = el.getBoundingClientRect();
      return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    };
    const scrim = document.querySelector('.scrim');
    return [document.querySelector('.fab'), document.querySelector('.tabbar')]
      .map((el) => scrim.contains(topAt(el)));
  });
  expect(covered).toEqual([true, true]);
});

// ── Reduced motion collapses every duration ────────────────────────────────

test('reduced motion makes transitions and entrances near-instant', async ({ page }) => {
  await open(page, '/dashboard', { reduced: true });
  await expect(page.getByText('Needs attention').first()).toBeVisible();
  const timing = await page.evaluate(() => {
    const seconds = (v) => Math.max(...v.split(',').map((t) => parseFloat(t) * (t.includes('ms') ? 0.001 : 1)));
    const btn = getComputedStyle(document.querySelector('.btn'));
    const board = getComputedStyle(document.querySelector('.dash > :nth-child(3)'));
    return {
      transition: seconds(btn.transitionDuration),
      entrance: seconds(board.animationDuration),
      delay: seconds(board.animationDelay),
    };
  });
  expect(timing.transition).toBeLessThanOrEqual(0.001);
  expect(timing.entrance).toBeLessThanOrEqual(0.001);
  expect(timing.delay).toBe(0);
});

// ── Nothing that moves pushes the page sideways ────────────────────────────

for (const width of [360, 390, 768, 1440]) {
  test(`no horizontal overflow while things animate at ${width}px`, async ({ page }) => {
    const api = await open(page, '/dashboard', { width });
    // Sample during the entrance, not only after it has settled.
    for (let i = 0; i < 4; i += 1) {
      expect(await overflow(page)).toBeLessThanOrEqual(0);
      await page.waitForTimeout(60);
    }
    await expect(page.getByText('Needs attention').first()).toBeVisible();
    api.fresh = true;
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await expect(page.locator('.toast')).toHaveCount(1);
    expect(await overflow(page)).toBeLessThanOrEqual(0);
    await page.getByRole('button', { name: /^Notifications/ }).click();
    expect(await overflow(page)).toBeLessThanOrEqual(0);
    await expect(page.getByRole('dialog', { name: 'Notifications' })).toBeVisible();
    expect(await overflow(page)).toBeLessThanOrEqual(0);
  });
}
