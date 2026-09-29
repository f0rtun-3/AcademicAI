// Password reset is switched off until students can receive the email
// (src/lib/features.js). In a real browser: the sign-in link still leads to
// the page, the page explains instead of asking for an email, and no reset
// request ever reaches the server - from there or from Settings.

import { test, expect } from '@playwright/test';
import { installMockApi, STUDENT } from './fixtures/mockApi.js';

const TITLE = 'Password reset isn’t available yet';
const resetRequests = (api) => api.requests.filter((r) => /\/api\/auth\/(forgot|reset)-password/.test(r.path));

test('sign in → forgot password → the unavailable state → back to sign in', async ({ page }) => {
  const errors = []; page.on('pageerror', (e) => errors.push(e.message));
  await page.setViewportSize({ width: 390, height: 844 });
  const api = await installMockApi(page, { session: null });
  await page.goto('/login');
  await page.getByRole('link', { name: 'Forgot your password?' }).click();
  await expect(page).toHaveURL(/\/forgot-password$/);
  await expect(page.getByRole('heading', { level: 1, name: TITLE })).toBeVisible();
  await expect(page.getByText('We’re still setting up secure email delivery for AcademicAI.', { exact: false })).toBeVisible();
  await expect(page.getByRole('textbox')).toHaveCount(0);
  await page.getByRole('link', { name: 'Back to sign in' }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Sign in' })).toBeVisible();
  expect(resetRequests(api)).toEqual([]);
  expect(errors).toEqual([]);
});

test('Settings: reset password is marked unavailable and explains why', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const api = await installMockApi(page, { session: STUDENT });
  await page.goto('/settings');
  await expect(page.getByText('Currently unavailable')).toBeVisible();
  await page.getByRole('button', { name: 'Reset password' }).click();
  await expect(page.getByRole('region', { name: TITLE })).toBeVisible();
  expect(resetRequests(api)).toEqual([]);
});
