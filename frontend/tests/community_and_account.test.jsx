// Members directory, the account menu, the Terms page, and where the Terms
// are linked from.

import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import CommunityMembers from '../src/components/CommunityMembers.jsx';
import AccountMenu from '../src/components/AccountMenu.jsx';
import TermsPage from '../src/pages/TermsPage.jsx';
import PublicFooter from '../src/components/PublicFooter.jsx';
import SignUp from '../src/pages/SignUp.jsx';
import { COMMUNITY, REP_SESSION, STUDENT_SESSION, mockApi, renderWithAuth } from './helpers.jsx';

const member = (user_id, full_name, role = 'STUDENT') => ({ user_id, full_name, role, status: 'ACTIVE' });
const FEW = [
  member(1, 'Ada Rep', 'VERIFIED_REP'), member(2, 'Bola Student'),
  member(3, 'Chinedu Obi'), member(4, 'Amaka Eze'),
];
const MANY = [
  ...FEW,
  ...['Tunde Bello', 'Zainab Musa', 'Ifeoma Nwosu', 'Kemi Ade', 'Seun Ola', 'Musa Garba']
    .map((name, i) => member(10 + i, name)),
];

function directory(members, session = STUDENT_SESSION) {
  mockApi({ '/auth/me': session, '/community/members': { members } });
  renderWithAuth(<CommunityMembers community={COMMUNITY} />);
}
const names = (group) => within(screen.getByRole('region', { name: group }))
  .getAllByRole('listitem').map((li) => li.querySelector('.member__name').firstChild.textContent);

describe('the members directory', () => {
  it('lists reps first, then students A to Z, and marks you', async () => {
    directory(FEW);
    await screen.findByRole('region', { name: 'Course reps' });
    expect(names('Course reps')).toEqual(['Ada Rep']);
    expect(names('Students')).toEqual(['Amaka Eze', 'Bola Student', 'Chinedu Obi']);
    // The rep's tenure comes from the community payload, in months.
    expect(screen.getByText('Course rep since September 2026')).toBeInTheDocument();
    // You, once.
    const you = screen.getByText('You');
    expect(you.closest('.member')).toHaveTextContent('Bola Student');
    expect(screen.getAllByText('You')).toHaveLength(1);
  });

  it('says the community once, not on every row, and shows nobody’s email', async () => {
    directory(FEW);
    await screen.findByRole('region', { name: 'Students' });
    expect(screen.getAllByText('Software Engineering · Level 200 · 2026/2027')).toHaveLength(1);
    expect(document.body.textContent).not.toMatch(/@/);
    expect(screen.getByText('people').parentElement).toHaveTextContent('4 people');
  });

  it('offers search only once the list is long enough to need it', async () => {
    directory(FEW);
    await screen.findByRole('region', { name: 'Students' });
    expect(screen.queryByLabelText('Find a member')).not.toBeInTheDocument();
  });

  it('searches by name, and says so plainly when nobody matches', async () => {
    directory(MANY);
    const search = await screen.findByLabelText('Find a member');
    fireEvent.change(search, { target: { value: 'musa' } });
    expect(names('Students')).toEqual(['Musa Garba', 'Zainab Musa']);
    expect(screen.queryByRole('region', { name: 'Course reps' })).not.toBeInTheDocument();

    fireEvent.change(search, { target: { value: 'nobody-here' } });
    expect(screen.getByText('No one called “nobody-here”')).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: 'Clear the search' })[0]);
    expect(names('Students')).toHaveLength(MANY.length - 1);
  });

  it('filters to course reps', async () => {
    directory(FEW);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Course reps (1)' }));
    expect(screen.getByRole('button', { name: 'Course reps (1)' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByRole('region', { name: 'Students' })).not.toBeInTheDocument();
    expect(names('Course reps')).toEqual(['Ada Rep']);
  });

  it('has a real empty state when you are the only member', async () => {
    directory([member(2, 'Bola Student')]);
    expect(await screen.findByText('It’s just you so far')).toBeInTheDocument();
  });

  it('has an error state with a retry', async () => {
    mockApi({ '/auth/me': STUDENT_SESSION,
              '/community/members': () => ({ __status: 500, error: 'server_error', message: 'boom' }) });
    renderWithAuth(<CommunityMembers community={COMMUNITY} />);
    expect(await screen.findByRole('button', { name: /try again|retry/i })).toBeInTheDocument();
  });
});

describe('the account menu', () => {
  async function openMenu(session = REP_SESSION) {
    mockApi({ '/auth/me': session });
    renderWithAuth(<AccountMenu />);
    const user = userEvent.setup();
    const avatar = await screen.findByRole('button', { name: `Account: ${session.user.full_name}` });
    await user.click(avatar);
    return { user, avatar, menu: screen.getByRole('menu', { name: 'Account' }) };
  }

  it('leads with who you are: name, role, community, address', async () => {
    const { menu } = await openMenu();
    expect(within(menu).getByText('Ada Rep')).toBeInTheDocument();
    expect(within(menu).getByText('Course rep')).toBeInTheDocument();
    expect(within(menu).getByText('Software Engineering · Level 200')).toBeInTheDocument();
    expect(within(menu).getByText('ada@babcock.edu.ng')).toBeInTheDocument();
    const items = within(menu).getAllByRole('menuitem').map((el) => el.textContent.trim());
    expect(items).toEqual(['Your profile', 'Your reminders', 'Community members', 'Settings', 'Log out']);
  });

  it('opens on its first item and moves with the arrow keys, wrapping', async () => {
    const { user, menu } = await openMenu();
    const items = within(menu).getAllByRole('menuitem');
    await waitFor(() => expect(items[0]).toHaveFocus());
    await user.keyboard('{ArrowDown}');
    expect(items[1]).toHaveFocus();
    await user.keyboard('{End}');
    expect(items[items.length - 1]).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(items[0]).toHaveFocus();
    await user.keyboard('{ArrowUp}');
    expect(items[items.length - 1]).toHaveFocus();
  });

  it('closes on Escape and gives focus back to the avatar', async () => {
    const { user, avatar } = await openMenu();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
    expect(avatar).toHaveFocus();
    expect(avatar).toHaveAttribute('aria-expanded', 'false');
  });

  it('closes on a click outside', async () => {
    const { user } = await openMenu();
    await user.click(document.body);
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
  });

  it('says so, rather than inventing one, when there is no community', async () => {
    const { menu } = await openMenu({ ...STUDENT_SESSION, membership: null });
    expect(within(menu).getByText('Not in a community yet')).toBeInTheDocument();
    expect(within(menu).queryByRole('menuitem', { name: 'Community members' })).not.toBeInTheDocument();
  });
});

describe('the Terms & Conditions', () => {
  it('is a numbered document with an effective date and a real contact', async () => {
    mockApi({ '/auth/me': { __status: 401 } });
    renderWithAuth(<TermsPage />);
    expect(screen.getByRole('heading', { level: 1, name: 'Terms & Conditions' })).toBeInTheDocument();
    expect(screen.getByText('Effective Tuesday 29 September 2026')).toBeInTheDocument();
    const sections = screen.getAllByRole('heading', { level: 2 });
    expect(sections).toHaveLength(17);
    expect(sections[0]).toHaveTextContent('1. Introduction and acceptance');
    expect(sections[16]).toHaveTextContent('17. Contact');
    const mail = screen.getAllByRole('link', { name: 'helloacademicai@gmail.com' });
    expect(mail[0]).toHaveAttribute('href', 'mailto:helloacademicai@gmail.com');
  });

  it('claims nothing the product does not do', async () => {
    mockApi({ '/auth/me': { __status: 401 } });
    renderWithAuth(<TermsPage />);
    const text = document.body.textContent;
    expect(text).toMatch(/not affiliated with, endorsed by or operated on behalf of any university/);
    expect(text).toMatch(/does not verify your identity/);
    expect(text).toMatch(/cannot guarantee/);
    expect(text).toMatch(/never publishes official information on its own/);
    // No invented promises.
    expect(text).not.toMatch(/we guarantee|guaranteed delivery|certified|ISO|GDPR compliant|99\.\d%|privacy policy/i);
  });
});

describe('where the Terms are linked from', () => {
  it('the landing footer, beside the other account links', () => {
    mockApi({ '/auth/me': { __status: 401 } });
    renderWithAuth(<PublicFooter />);
    expect(screen.getByRole('link', { name: 'Terms & Conditions' })).toHaveAttribute('href', '/terms');
  });

  it('the sign-up form, in a new tab so the form is not lost', async () => {
    mockApi({ '/auth/me': { __status: 401 }, '/universities': { universities: [] } });
    renderWithAuth(<SignUp />);
    const link = await screen.findByRole('link', { name: 'Terms & Conditions' });
    expect(link).toHaveAttribute('href', '/terms');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link.closest('label')).toHaveTextContent('I agree to the Terms & Conditions.');
  });
});
