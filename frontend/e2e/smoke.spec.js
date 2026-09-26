// Smoke test: the app boots in a real browser and responds to input.
//
// Stays on the public pages, which make no API calls for an anonymous
// visitor, so it passes without the Flask backend running.

import { test, expect } from '@playwright/test';

test('landing page loads and leads to a working sign-in form', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await page.goto('/');

  await expect(page).toHaveTitle(/AcademicAI/);
  await expect(page.getByRole('heading', { level: 1 }))
    .toHaveText('Your academic life, in one place you can trust.');

  await page.getByRole('banner').getByRole('link', { name: 'Log in' }).click();

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Sign in' })).toBeVisible();

  const email = page.getByLabel('Student email');
  await email.fill('student@example.edu');
  await expect(email).toHaveValue('student@example.edu');

  expect(errors).toEqual([]);
});
