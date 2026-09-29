// The sign-up agreement, the fixed name, and the phone menu's page lock.

import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SignUp from '../src/pages/SignUp.jsx';
import ProfilePage from '../src/pages/ProfilePage.jsx';
import AccountMenu from '../src/components/AccountMenu.jsx';
import { isScrollLocked, lockScroll } from '../src/lib/scrollLock.js';
import { TERMS_VERSION } from '../src/lib/terms.js';
import { REP_SESSION, STUDENT_SESSION, mockApi, renderWithAuth } from './helpers.jsx';

const REGISTRY = { universities: [{ id: 1, name: 'Babcock University',
  domains: [{ domain: 'student.babcock.edu.ng', domain_type: 'STUDENT' }] }] };

// Change events rather than typed keystrokes: these tests are about the
// agreement, and typing nine fields key by key is what made them slow.
async function fillForm(user) {
  await screen.findByLabelText('University');
  await waitFor(() => expect(screen.getByLabelText('University').tagName).toBe('SELECT'));
  const set = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
  set('Full name', 'Ada Student');
  set('Student email', 'ada@student.babcock.edu.ng');
  set('Password', 'Password123');
  set('Confirm password', 'Password123');
  await user.selectOptions(screen.getByLabelText('University'), 'Babcock University');
  set('Department', 'Software Engineering');
  set('Level', '200');
  set('Academic session', '2026/2027');
  set('Matric Number', '21/1234');
}
// jsdom's name calculation adds a space after the inline link ("Conditions .");
// a browser does not. Matched from the start, the words are the check.
const box = () => screen.getByRole('checkbox', { name: /^I agree to the Terms & Conditions/ });
const create = () => screen.getByRole('button', { name: 'Create account' });
const describedBy = (el) => (el.getAttribute('aria-describedby') || '').split(' ')
  .map((id) => document.getElementById(id)?.textContent ?? '').join(' ');

describe('sign-up: the Terms agreement', () => {
  it('starts unticked, and the button says it is not ready yet', async () => {
    mockApi({ '/universities': REGISTRY });
    renderWithAuth(<SignUp />, { token: null });
    await screen.findByLabelText('University');
    expect(box()).not.toBeChecked();
    expect(create()).toHaveAttribute('aria-disabled', 'true');
    expect(describedBy(create())).toMatch('Agree to the Terms & Conditions above to create your account.');
  });

  it('does not create an account while unticked - the box says why and takes focus', async () => {
    const calls = mockApi({ '/universities': REGISTRY });
    renderWithAuth(<SignUp />, { token: null });
    const user = userEvent.setup();
    await fillForm(user);
    await user.click(create());

    await waitFor(() => expect(box()).toHaveFocus());
    expect(box()).toHaveAttribute('aria-invalid', 'true');
    expect(describedBy(box())).toMatch('Agree to the Terms & Conditions to create your account.');
    expect(calls.some((c) => c.path === '/auth/register')).toBe(false);
  });

  it('once ticked, submits - with the acceptance and the Terms version', async () => {
    const calls = mockApi({
      '/universities': REGISTRY,
      'POST /auth/register': { user: { id: 9 }, next_step: 'verify_email' },
    });
    renderWithAuth(<SignUp />, { token: null });
    const user = userEvent.setup();
    await fillForm(user);
    await user.click(box());
    expect(box()).toBeChecked();
    expect(create()).not.toHaveAttribute('aria-disabled');
    await user.click(create());

    await waitFor(() => expect(calls.some((c) => c.path === '/auth/register')).toBe(true));
    const sent = calls.find((c) => c.path === '/auth/register').body;
    expect(sent.accept_terms).toBe(true);
    expect(sent.terms_version).toBe(TERMS_VERSION);
    expect(TERMS_VERSION).toBe('2026-09-29');
  });

  it('ticking the box answers its error', async () => {
    mockApi({ '/universities': REGISTRY });
    renderWithAuth(<SignUp />, { token: null });
    const user = userEvent.setup();
    await fillForm(user);
    await user.click(create());
    await waitFor(() => expect(box()).toHaveAttribute('aria-invalid', 'true'));
    await user.click(box());
    expect(box()).not.toHaveAttribute('aria-invalid');
  });

  it('the link goes to /terms in a new tab, and following it does not tick the box', async () => {
    mockApi({ '/universities': REGISTRY });
    renderWithAuth(<SignUp />, { token: null });
    await screen.findByLabelText('University');
    const link = within(box().closest('label')).getByRole('link', { name: 'Terms & Conditions' });
    expect(link).toHaveAttribute('href', '/terms');
    expect(link).toHaveAttribute('target', '_blank');
    fireEvent.click(link);
    expect(box()).not.toBeChecked();
  });

  it('puts the backend’s refusal of the agreement beside the box', async () => {
    mockApi({
      '/universities': REGISTRY,
      'POST /auth/register': { __status: 400, error: 'validation_error',
        message: 'The Terms & Conditions have been updated since this page was opened.',
        details: { field: 'accept_terms', terms_version: '2027-01-01' } },
    });
    renderWithAuth(<SignUp />, { token: null });
    const user = userEvent.setup();
    await fillForm(user);
    await user.click(box());
    await user.click(create());
    await waitFor(() => expect(box()).toHaveAttribute('aria-invalid', 'true'));
    expect(describedBy(box())).toMatch('have been updated');
  });
});

describe('profile: the name is fixed', () => {
  it('shows the name as read-only record data, with no way to change it', async () => {
    mockApi({ '/auth/me': STUDENT_SESSION });
    renderWithAuth(<ProfilePage />);
    const record = (await screen.findByText('Academic record')).closest('.pblock');
    expect(within(record).getByText('Read-only')).toBeInTheDocument();
    expect(within(record).getByText('Name')).toBeInTheDocument();
    expect(within(record).getByText('Bola Student')).toBeInTheDocument();
    expect(record).toHaveTextContent(/Your name stays as registered/);
    // No field, and no control anywhere on the page, to change it.
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    const controls = [...screen.queryAllByRole('button'), ...screen.queryAllByRole('link')]
      .map((el) => el.textContent.trim());
    expect(controls.filter((t) => /name|rename/i.test(t))).toEqual([]);
    expect(document.body.textContent).not.toMatch(/(edit|change|update) (your )?name/i);
  });
});

describe('the page lock', () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it('locks the root, and lifts only when the last holder lets go', () => {
    const first = lockScroll();
    const second = lockScroll();
    expect(document.documentElement).toHaveClass('is-scroll-locked');
    first();
    expect(isScrollLocked()).toBe(true);
    second();
    expect(document.documentElement).not.toHaveClass('is-scroll-locked');
    expect(isScrollLocked()).toBe(false);
  });

  it('cancels wheel and touch scrolling of the page, but lets the sheet scroll', () => {
    const sheet = document.createElement('div');
    const inner = document.createElement('p');
    sheet.appendChild(inner);
    document.body.appendChild(sheet);
    Object.defineProperties(sheet, { scrollHeight: { value: 800 }, clientHeight: { value: 400 } });
    sheet.scrollTop = 100;
    const unlock = lockScroll(sheet);

    const wheel = (target, deltaY) => {
      const event = new WheelEvent('wheel', { deltaY, bubbles: true, cancelable: true });
      target.dispatchEvent(event);
      return event.defaultPrevented;
    };
    expect(wheel(document.body, 50)).toBe(true);    // the page: held
    expect(wheel(inner, 50)).toBe(false);           // the sheet, with room to go: scrolls
    sheet.scrollTop = 400;                           // at its end
    expect(wheel(inner, 50)).toBe(true);            // no scroll chaining into the page

    const touch = (target, from, to) => {
      target.dispatchEvent(new TouchEvent('touchstart', { bubbles: true, touches: [{ clientY: from }] }));
      const move = new TouchEvent('touchmove', { bubbles: true, cancelable: true, touches: [{ clientY: to }] });
      target.dispatchEvent(move);
      return move.defaultPrevented;
    };
    expect(touch(document.body, 300, 200)).toBe(true);   // a drag on the backdrop: held
    expect(touch(inner, 300, 400)).toBe(false);          // dragging the sheet back up: scrolls
    unlock();
    sheet.remove();
  });

  it('puts the page back exactly where it was, instantly', () => {
    const scrollTo = vi.fn();
    vi.spyOn(window, 'scrollTo').mockImplementation(scrollTo);
    Object.defineProperty(window, 'scrollY', { configurable: true, value: 640 });
    const unlock = lockScroll();
    Object.defineProperty(window, 'scrollY', { configurable: true, value: 0 });  // something moved it
    unlock();
    expect(scrollTo).toHaveBeenCalledWith({ left: 0, top: 640, behavior: 'instant' });
    Object.defineProperty(window, 'scrollY', { configurable: true, value: 0 });
  });
});

describe('the account menu on a phone is modal', () => {
  const realMatchMedia = window.matchMedia;
  afterEach(() => { window.matchMedia = realMatchMedia; });

  async function openSheet() {
    window.matchMedia = (query) => ({
      matches: query === '(max-width: 639px)', media: query,
      addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
    });
    mockApi({ '/auth/me': REP_SESSION });
    const user = userEvent.setup();
    const { container } = renderWithAuth(
      <>
        <AccountMenu />
        <main id="content"><button type="button">Behind the sheet</button></main>
        <nav className="tabbar"><a href="/calendar">Calendar</a></nav>
      </>,
    );
    const avatar = await screen.findByRole('button', { name: 'Account: Ada Rep' });
    await user.click(avatar);
    return { user, avatar, container };
  }

  it('is a modal dialog holding the menu, and locks the page', async () => {
    await openSheet();
    const dialog = screen.getByRole('dialog', { name: 'Account' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(within(dialog).getByRole('menu', { name: 'Account' })).toBeInTheDocument();
    expect(document.documentElement).toHaveClass('is-scroll-locked');
  });

  it('makes everything behind it unreachable, and gives it back on close', async () => {
    const { user, container } = await openSheet();
    expect(container.querySelector('#content')).toHaveAttribute('inert');
    expect(container.querySelector('.tabbar')).toHaveAttribute('inert');
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(container.querySelector('#content')).not.toHaveAttribute('inert');
    expect(document.documentElement).not.toHaveClass('is-scroll-locked');
  });

  it('keeps Tab inside the sheet, and the arrow keys still move through the menu', async () => {
    const { user } = await openSheet();
    const dialog = screen.getByRole('dialog', { name: 'Account' });
    const items = within(dialog).getAllByRole('menuitem');
    await waitFor(() => expect(items[0]).toHaveFocus());
    await user.keyboard('{ArrowDown}');
    expect(items[1]).toHaveFocus();
    // From the last focusable thing in the sheet, Tab wraps to the first.
    items[items.length - 1].focus();
    await user.tab();
    expect(dialog.contains(document.activeElement)).toBe(true);
    await user.tab({ shift: true });
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it('closes from the backdrop and returns focus to the avatar', async () => {
    const { avatar, container } = await openSheet();
    fireEvent.mouseDown(container.querySelector('.acct__scrim'));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(avatar).toHaveFocus();
  });

  it('on a laptop it is still a plain menu that does not lock the page', async () => {
    mockApi({ '/auth/me': REP_SESSION });
    const user = userEvent.setup();
    renderWithAuth(<AccountMenu />);
    await user.click(await screen.findByRole('button', { name: 'Account: Ada Rep' }));
    expect(screen.getByRole('menu', { name: 'Account' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(document.documentElement).not.toHaveClass('is-scroll-locked');
  });
});

