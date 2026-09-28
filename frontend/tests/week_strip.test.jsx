import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import WeekStrip from '../src/components/WeekStrip.jsx';

// The dashboard's week at a glance: today and the six days after it, one
// mark per thing due, counted from the events the dashboard already has.
describe('the week strip', () => {
  const events = [
    { id: 1, event_date: '2026-09-26', status: 'SCHEDULED' },
    { id: 2, event_date: '2026-09-28', status: 'SCHEDULED' },
    { id: 3, event_date: '2026-09-28', status: 'SCHEDULED' },
    { id: 4, event_date: '2026-09-29', status: 'CANCELLED' },
    { id: 5, event_date: '2026-10-09', status: 'SCHEDULED' },   // beyond the week
  ];

  it('shows seven days from today, with today first and marked', () => {
    render(<WeekStrip events={events} today="2026-09-26" />);
    const days = within(screen.getByRole('list', { name: 'Your next seven days' }))
      .getAllByRole('listitem');
    expect(days).toHaveLength(7);
    expect(days[0]).toHaveClass('wkstrip__day--today');
    expect(days[0]).toHaveTextContent('Today, Saturday 26 September: 1 due');
    expect(days[6]).toHaveTextContent('Friday 2 October: nothing due');
  });

  it('counts what is due and says a cancellation happened, in words', () => {
    render(<WeekStrip events={events} today="2026-09-26" />);
    expect(screen.getByText('Monday 28 September: 2 due')).toBeInTheDocument();
    expect(screen.getByText('Tuesday 29 September: nothing due, 1 cancelled'))
      .toBeInTheDocument();
    // Nothing outside the seven days is counted.
    expect(screen.queryByText(/9 October/)).not.toBeInTheDocument();
  });
});
