// The Community sub-navigation, shared by every Community route.
//
//   /community             Overview
//   /community/elections   Elections
//   /community/membership  Membership
//   /community/manage      Manage (verified rep only)
//
// Each section is a real route, so it is linkable, survives a refresh and is
// what the back button returns to. NavLink marks the current one with
// aria-current="page". Manage is a SUB-route of Community rather than a fifth
// top-level destination: a role changes what is inside the shell, never the
// shell itself, and the rail keeps Community highlighted throughout.

import { NavLink } from 'react-router-dom';

export default function CommunityNav({ isRep }) {
  const items = [
    { to: '/community', label: 'Overview', end: true },
    { to: '/community/elections', label: 'Elections' },
    { to: '/community/membership', label: 'Membership' },
  ];
  // Absent for a student, not disabled.
  if (isRep) items.push({ to: '/community/manage', label: 'Manage' });

  return (
    <nav className="subnav" aria-label="Community sections">
      {items.map((item) => (
        <NavLink key={item.to} to={item.to} end={item.end}>{item.label}</NavLink>
      ))}
    </nav>
  );
}
