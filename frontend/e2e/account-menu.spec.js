// The account menu on a phone is a modal bottom sheet: the page behind it is
// held exactly where it was - wheel, trackpad, touch and keyboard - and put
// back to the same pixel when the sheet closes. On a laptop it is a popover
// and the page scrolls as normal. (components/AccountMenu.jsx,
// lib/scrollLock.js)

import { test, expect } from '@playwright/test';
import { installMockApi, STUDENT } from './fixtures/mockApi.js';

async function open(page, { width, height, path = '/dashboard' }) {
  await page.setViewportSize({ width, height });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.clock.setFixedTime(new Date('2026-09-26T10:00:00Z'));
  await installMockApi(page, { session: STUDENT });
  await page.goto(path);
  await expect(page.getByText('Needs attention').first()).toBeVisible();
}
const scrollY = (page) => page.evaluate(() => Math.round(window.scrollY));
// On a phone the top bar scrolls away with the page, so a person opens the
// menu near the top. To prove the lock holds from ANY position, these open it
// with a click event rather than Playwright's click, which would first scroll
// the (off-screen) avatar into view and move the page itself.
const openMenu = (page) => page.getByRole('button', { name: /^Account/ }).dispatchEvent('click');
const scrollTo = (page, y) => page.evaluate(
  (top) => window.scrollTo({ top, behavior: 'instant' }), y);

// A real finger drag, through the browser's own touch pipeline.
async function drag(page, x, fromY, toY) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 1 });
  const touch = (type, y) => cdp.send('Input.dispatchTouchEvent', {
    type, touchPoints: type === 'touchEnd' ? [] : [{ x, y }] });
  await touch('touchStart', fromY);
  for (let i = 1; i <= 8; i += 1) await touch('touchMove', fromY + ((toY - fromY) * i) / 8);
  await touch('touchEnd', toY);
}

test('phone: the page behind the sheet is held exactly where it was', async ({ page }) => {
  await open(page, { width: 390, height: 844 });
  await scrollTo(page, 500);
  const before = await scrollY(page);
  expect(before).toBe(500);

  await openMenu(page);
  const sheet = page.getByRole('dialog', { name: 'Account' });
  await expect(sheet).toBeVisible();
  await expect(sheet).toHaveAttribute('aria-modal', 'true');
  await expect(page.locator('html')).toHaveClass(/is-scroll-locked/);

  // Wheel and trackpad over the dimmed page.
  await page.mouse.move(195, 120);
  await page.mouse.wheel(0, 900);
  await page.waitForTimeout(250);
  expect(await scrollY(page)).toBe(before);
  // A finger dragging the backdrop.
  await drag(page, 195, 250, 60);
  await page.waitForTimeout(250);
  expect(await scrollY(page)).toBe(before);
  // The keyboard.
  await page.keyboard.press('PageDown');
  await page.keyboard.press('Space');
  await page.waitForTimeout(150);
  expect(await scrollY(page)).toBe(before);
  // Nothing behind it can be reached.
  await expect(page.locator('#content')).toHaveAttribute('inert', '');

  // Closing puts it back to the same pixel, and focus on the avatar.
  await page.keyboard.press('Escape');
  await expect(sheet).toHaveCount(0);
  await expect(page.locator('html')).not.toHaveClass(/is-scroll-locked/);
  expect(await scrollY(page)).toBe(before);
  await expect(page.getByRole('button', { name: /^Account/ })).toBeFocused();
  // ...and the page scrolls normally again.
  await page.mouse.wheel(0, 300);
  await expect.poll(() => scrollY(page)).toBeGreaterThan(before);
});

test('phone: a real tap on the avatar near the top, then the page is held there', async ({ page }) => {
  await open(page, { width: 390, height: 844 });
  await scrollTo(page, 24);                        // the avatar is still on screen
  await page.getByRole('button', { name: /^Account/ }).click();
  await expect(page.getByRole('dialog', { name: 'Account' })).toBeVisible();
  // Wherever the page was when the sheet opened is where it must stay.
  const at = await scrollY(page);
  await drag(page, 195, 300, 80);
  await page.mouse.wheel(0, 600);
  await page.waitForTimeout(250);
  expect(await scrollY(page)).toBe(at);
  await page.keyboard.press('Escape');
  expect(await scrollY(page)).toBe(at);
});

test('phone: tapping the backdrop closes the sheet and restores the page', async ({ page }) => {
  await open(page, { width: 390, height: 844 });
  await scrollTo(page, 420);
  await openMenu(page);
  await expect(page.getByRole('dialog', { name: 'Account' })).toBeVisible();
  await page.mouse.click(195, 90);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(await scrollY(page)).toBe(420);
  await expect(page.getByRole('button', { name: /^Account/ })).toBeFocused();
});

test('phone: the sheet scrolls itself when it is taller than the screen', async ({ page }) => {
  await open(page, { width: 390, height: 460 });
  await scrollTo(page, 300);
  await openMenu(page);
  const sheet = page.getByRole('dialog', { name: 'Account' });
  await expect(sheet).toBeVisible();
  const fits = await sheet.evaluate((el) => el.scrollHeight <= el.clientHeight);
  expect(fits).toBe(false);                      // taller than the space it has
  const box = await sheet.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.wheel(0, 400);
  await expect.poll(() => sheet.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
  expect(await scrollY(page)).toBe(300);          // the sheet moved, the page did not
  // Its last row, Log out, is reachable by scrolling.
  await expect(page.getByRole('menuitem', { name: 'Log out' })).toBeInViewport();
});

test('phone: choosing a page from the sheet does not drag the old position along', async ({ page }) => {
  await open(page, { width: 390, height: 844 });
  await scrollTo(page, 600);
  await openMenu(page);
  await page.getByRole('menuitem', { name: 'Your reminders' }).click();
  await expect(page).toHaveURL(/\/reminders$/);
  await expect(page.locator('html')).not.toHaveClass(/is-scroll-locked/);
  expect(await scrollY(page)).toBeLessThan(600);
});

test('laptop: the popover leaves the page scrolling as normal', async ({ page }) => {
  await open(page, { width: 1280, height: 800 });
  await scrollTo(page, 200);
  await page.getByRole('button', { name: /^Account/ }).click();
  await expect(page.getByRole('menu', { name: 'Account' })).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('html')).not.toHaveClass(/is-scroll-locked/);
  await page.mouse.move(640, 600);
  await page.mouse.wheel(0, 300);
  await expect.poll(() => scrollY(page)).toBeGreaterThan(200);
});
