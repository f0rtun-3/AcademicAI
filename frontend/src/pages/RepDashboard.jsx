import { useId, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { useResource } from '../components/useResource.js';
import {
  EmptyState, ErrorBanner, ErrorState, Loading, SuccessBanner, Unauthorized,
} from '../components/States.jsx';
import {
  Board, Field, PageHeader, Panel, Row, StateChip, StatusBadge, Tile, longDate, whenParts,
} from '../components/ui.jsx';
import {
  IconAdd, IconBook, IconCalendar, IconClose, IconMegaphone, IconShield, IconUser,
} from '../components/icons.jsx';
import CommunityNav from '../components/CommunityNav.jsx';
import { dayLong, dayShort, spokenDay } from '../lib/vocabulary.js';

// PROGRESSIVE DISCLOSURE for the "add" forms. Manage used to be one long
// column in which every board ended in an open form, so the page read as
// forms first and records second. Now each board shows what exists, and the
// form it can add to opens from one button - the same form, the same fields,
// nothing removed. `always` is for a section with nothing in it yet, where
// adding is the only thing to do: the form is simply there, with no toggle.
function AddForm({ label, children, always = false }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  if (always) return <div className="addform__body">{children}</div>;
  return (
    <div className={`addform${open ? ' addform--open' : ''}`}>
      <button type="button" className="btn btn--secondary addform__toggle"
              aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}>
        {open ? <IconClose size={16} /> : <IconAdd size={16} />}
        {open ? 'Close' : label}
      </button>
      {open && <div className="addform__body" id={id}>{children}</div>}
    </div>
  );
}

function CourseManager({ courses, onChanged, setError }) {
  const [form, setForm] = useState({ code: '', title: '' });
  const [editing, setEditing] = useState(null);

  async function add(event) {
    event.preventDefault();
    try {
      await api.post('/community/courses', form);
      setForm({ code: '', title: '' });
      onChanged();
    } catch (err) {
      setError(err);
    }
  }

  async function remove(course) {
    try {
      await api.del(`/community/courses/${course.id}`);
      onChanged();
    } catch (err) {
      // Removal is refused while scheduled events or active timetable entries
      // still reference the course. Name them so the rep knows what to clear.
      const events = err.details?.blocking_events ?? [];
      const entries = err.details?.blocking_timetable_entries ?? [];
      if (events.length || entries.length) {
        const names = [
          ...events.map((e) => e.title),
          ...entries.map((t) => `${t.day_of_week} ${t.start_time || ''}`.trim()),
        ].join(', ');
        setError(`${err.message} Still attached: ${names}.`);
      } else {
        setError(err);
      }
    }
  }

  async function saveEdit(event, course) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      await api.put(`/community/courses/${course.id}`, {
        code: data.get('code'), title: data.get('title'),
      });
      setEditing(null);
      onChanged();
    } catch (err) {
      setError(err);
    }
  }

  // The add form is the board's FOOTER, not a last row. A form pretending to
  // be a record made the boundary between "what exists" and "what you are
  // adding" invisible; a footer is visibly not one of the rows above it.
  const addForm = (
    <form className="form-grid form-grid--2" onSubmit={add}>
      <Field id="course-code" label="Course code" required value={form.code}
             onChange={(e) => setForm({ ...form, code: e.target.value })} />
      <Field id="course-title" label="Title" value={form.title}
             onChange={(e) => setForm({ ...form, title: e.target.value })} />
      <div style={{ gridColumn: '1 / -1' }}>
        <button type="submit" className="btn btn--secondary">Add course</button>
      </div>
    </form>
  );

  return (
    <Board title="Courses" icon={IconBook}
           foot={<AddForm label="Add a course" always={courses.length === 0}>{addForm}</AddForm>}>
      <div>
        {courses.length === 0 && (
          <EmptyState title="No courses yet"
                      message="Add the courses this community takes. Students enrol
                               themselves, and only enrolled students are notified." />
        )}
        {courses.map((course) => (
          editing === course.id ? (
            <div className="brow brow--flat" key={course.id}>
              <form className="form-grid form-grid--2" style={{ width: '100%' }}
                    onSubmit={(e) => saveEdit(e, course)}>
                <Field id={`c-code-${course.id}`} label="Course code" name="code" required
                       defaultValue={course.code} />
                <Field id={`c-title-${course.id}`} label="Title" name="title"
                       defaultValue={course.title || ''} />
                <div className="row-x stackable" style={{ gridColumn: '1 / -1' }}>
                  <button type="submit" className="btn btn--primary">Save course</button>
                  <button type="button" className="btn btn--secondary"
                          onClick={() => setEditing(null)}>Cancel editing</button>
                </div>
              </form>
            </div>
          ) : (
            <Row key={course.id} title={course.code} meta={course.title}
                 side={<>
                   <button type="button" className="btn btn--secondary"
                           data-testid={`edit-course-${course.id}`}
                           onClick={() => setEditing(course.id)}>Edit</button>
                   {/* No dialog: the backend refuses while records depend on
                       this course and names them. That response IS the
                       confirmation. */}
                   <button type="button" className="btn btn--danger"
                           onClick={() => remove(course)}>Remove</button>
                 </>} />
          )
        ))}
      </div>
    </Board>
  );
}

function TimetableManager({ timetable, courses, onChanged, setError }) {
  const DAYS = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY'];
  const [form, setForm] = useState({
    title: '', course_id: '', day_of_week: 'MONDAY', start_time: '', venue: '',
  });
  const [editing, setEditing] = useState(null);

  // The entry's version travels with the edit, so a stale form loses to a
  // concurrent change instead of overwriting it. The backend decides; a 409
  // is reported rather than retried.
  async function saveEdit(event, entry) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const courseId = data.get('course_id');
    try {
      await api.put(`/community/timetable/${entry.id}`, {
        title: data.get('title') || null,
        course_id: courseId ? Number(courseId) : null,
        day_of_week: data.get('day_of_week'),
        start_time: data.get('start_time') || null,
        venue: data.get('venue') || null,
        expected_version: entry.version,
      });
      setEditing(null);
      onChanged();
    } catch (err) {
      setError(err);
    }
  }

  async function add(event) {
    event.preventDefault();
    try {
      await api.post('/community/timetable', {
        ...form, course_id: form.course_id ? Number(form.course_id) : null,
        start_time: form.start_time || null, venue: form.venue || null,
      });
      setForm({ title: '', course_id: '', day_of_week: 'MONDAY', start_time: '', venue: '' });
      onChanged();
    } catch (err) {
      setError(err);
    }
  }

  const addForm = (
    <form className="form-grid form-grid--2" onSubmit={add}>
      <Field id="tt-title" label="Class title" value={form.title}
             onChange={(e) => setForm({ ...form, title: e.target.value })} />
      <Field id="tt-course" label="Course">
        {(props) => (
          <select {...props} value={form.course_id}
                  onChange={(e) => setForm({ ...form, course_id: e.target.value })}>
            <option value="">No specific course</option>
            {courses.map((c) => <option key={c.id} value={c.id}>{c.code}</option>)}
          </select>
        )}
      </Field>
      <Field id="tt-day" label="Day">
        {(props) => (
          <select {...props} value={form.day_of_week}
                  onChange={(e) => setForm({ ...form, day_of_week: e.target.value })}>
            {DAYS.map((d) => <option key={d} value={d}>{dayLong(d)}</option>)}
          </select>
        )}
      </Field>
      <Field id="tt-time" label="Start time" placeholder="HH:MM" value={form.start_time}
             onChange={(e) => setForm({ ...form, start_time: e.target.value })} />
      <Field id="tt-venue" label="Venue" value={form.venue}
             onChange={(e) => setForm({ ...form, venue: e.target.value })} />
      <div style={{ gridColumn: '1 / -1' }}>
        <button type="submit" className="btn btn--secondary">Add class</button>
      </div>
    </form>
  );

  return (
    <Board title="Timetable" icon={IconCalendar}
           foot={<AddForm label="Add a class" always={timetable.length === 0}>{addForm}</AddForm>}>
      <div>
        {timetable.length === 0 && (
          <EmptyState title="No timetable yet"
                      message="A class added here repeats every week. One-off events are
                               published from Add message instead." />
        )}
        {timetable.map((entry) => (
          /* `brow--flat` drops the left column, which the edit form needs and
             the display row does not: the row has a day/time column like every
             other row in the product. */
          <div className={editing === entry.id ? 'brow brow--flat' : 'brow'} key={entry.id}>
            {editing === entry.id ? (
              /* These were bare <label>/<input> pairs, so the design system's
                 control styling — which is scoped to `.field` — never reached
                 them and they rendered as raw browser inputs inside an
                 otherwise styled screen. The ids are unchanged. */
              <form className="form-grid form-grid--2" style={{ width: '100%' }}
                    onSubmit={(e) => saveEdit(e, entry)}>
                <Field id={`tt-e-title-${entry.id}`} label="Class title" name="title"
                       defaultValue={entry.title || ''} />
                <Field id={`tt-e-course-${entry.id}`} label="Course">
                  {(props) => (
                    <select {...props} name="course_id" defaultValue={entry.course_id ?? ''}>
                      <option value="">No specific course</option>
                      {courses.map((c) => <option key={c.id} value={c.id}>{c.code}</option>)}
                    </select>
                  )}
                </Field>
                <Field id={`tt-e-day-${entry.id}`} label="Day">
                  {(props) => (
                    <select {...props} name="day_of_week" defaultValue={entry.day_of_week}>
                      {DAYS.map((d) => <option key={d} value={d}>{dayLong(d)}</option>)}
                    </select>
                  )}
                </Field>
                <Field id={`tt-e-time-${entry.id}`} label="Start time" name="start_time"
                       placeholder="HH:MM" defaultValue={entry.start_time || ''} />
                <Field id={`tt-e-venue-${entry.id}`} label="Venue" name="venue"
                       defaultValue={entry.venue || ''} />
                <div className="row-x stackable" style={{ gridColumn: '1 / -1' }}>
                  <button type="submit" className="btn btn--primary">Save class</button>
                  <button type="button" className="btn btn--secondary"
                          onClick={() => setEditing(null)}>Cancel editing</button>
                </div>
              </form>
            ) : (
              <>
                {/* Same column as the student-facing timetable: the day in
                    the fixed left column, the venue in the metadata. */}
                <div className="brow__when">
                  <strong>{dayShort(entry.day_of_week)}</strong>
                  {entry.start_time ?? '—'}
                </div>
                <div className="brow__main">
                  <div className="brow__title">
                    {entry.title ?? entry.course_code ?? 'Class'}
                  </div>
                  <div className="brow__meta">
                    {entry.venue ?? 'Venue not specified'}
                  </div>
                </div>
                <div className="brow__side">
                  <button type="button" className="btn btn--secondary"
                          data-testid={`edit-timetable-${entry.id}`}
                          onClick={() => setEditing(entry.id)}>Edit</button>
                  <button type="button" className="btn btn--danger"
                          data-testid={`remove-timetable-${entry.id}`}
                          onClick={async () => {
                            try {
                              await api.del(`/community/timetable/${entry.id}`);
                              onChanged();
                            } catch (err) { setError(err); }
                          }}>Remove</button>
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    </Board>
  );
}

export default function RepDashboard() {
  const { isRep } = useAuth();
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [editingAnnouncement, setEditingAnnouncement] = useState(null);

  const resource = useResource(() => Promise.all([
    api.get('/dashboard'),
    api.get('/community/courses'),
    api.get('/community/timetable'),
    api.get('/rep/candidates'),
    api.get('/community/calendar'),
    api.get('/community/announcements'),
  ]).then(([dashboard, courses, timetable, candidates, calendar, announcements]) => ({
    dashboard, courses: courses.courses, timetable: timetable.timetable,
    candidates: candidates.candidates, calendar: calendar.calendar,
    announcements: announcements.announcements,
  })));

  if (!isRep) {
    // Absent rather than disabled, and with a route onward - never a bare 403.
    return (
      <Unauthorized message="Only a verified course rep can open Manage."
                   action={<Link className="btn btn--secondary" to="/community">
                     Back to Community
                   </Link>} />
    );
  }
  if (resource.status === 'loading') return <Loading label="Loading rep tools…" />;
  if (resource.status === 'error') {
    return <ErrorState message={resource.error} onRetry={resource.reload} />;
  }

  const { dashboard, courses, timetable, candidates, calendar, announcements } = resource.data;
  const rep = dashboard.rep ?? { pending_requests: [] };

  async function respond(userId, decision) {
    try {
      await api.post(`/community/requests/${userId}/${decision}`);
      setNotice(decision === 'approve' ? 'Student approved.' : 'Request rejected.');
      resource.reload();
    } catch (err) {
      setError(err);
    }
  }

  async function saveAnnouncement(event, item) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api.put(`/community/announcements/${item.id}`, {
        title: form.get('title'), body: form.get('body'),
        expected_version: item.version,
      });
      setEditingAnnouncement(null);
      setNotice('Announcement updated.');
      resource.reload();
    } catch (err) {
      setError(err);
    }
  }

  async function withdrawAnnouncement(item) {
    try {
      await api.del(`/community/announcements/${item.id}`);
      setNotice('Announcement withdrawn.');
      resource.reload();
    } catch (err) {
      setError(err);
    }
  }

  async function announce(event) {
    event.preventDefault();
    const data = new FormData(event.target);
    try {
      await api.post('/community/announcements', {
        title: data.get('title'), body: data.get('body'),
      });
      event.target.reset();
      setNotice('Announcement published.');
      resource.reload();
    } catch (err) {
      setError(err);
    }
  }

  async function uploadCalendar(event) {
    event.preventDefault();
    const data = new FormData(event.target);
    try {
      await api.post('/community/calendar', { raw_text: data.get('raw_text') });
      event.target.reset();
      setNotice('Academic calendar uploaded.');
      resource.reload();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <div className="stack stack--loose">
      <PageHeader
        eyebrow={`${dashboard.community.department} · Level ${dashboard.community.level}`
                 + ` · ${dashboard.community.academic_session}`}
        title="Manage"
        lede="Publish and look after your community's official information. Everything
              you publish here is shown as published by you." />

      <CommunityNav isRep />

      <SuccessBanner message={notice} onDismiss={() => setNotice(null)} />
      <ErrorBanner message={error} onDismiss={() => setError(null)} />

      {/* Manage, organised: a section index beside the work, the counts as a
          row of figures, then three named groups - who is in the community,
          its academic records, and what is said to it. Every tool that was
          here still is; they are grouped by what they are for. */}
      <div className="manage">
        <nav className="manage__nav" aria-label="Manage sections">
          <a href="#m-people">People</a>
          <a href="#m-records">Academic records</a>
          <a href="#m-comms">Communication</a>
        </nav>

        <div className="manage__body">
          {/* Tiles are spent here and nowhere else: in Manage these counts ARE
              the point. No denominator on reps - the vacancy cap is a backend
              rule and is not in any response, so it is not invented here (C·3). */}
          <div className="tiles glance">
            <Tile n={rep.student_count ?? 0} label="students" />
            <Tile n={rep.rep_count ?? 0}
                  label={`verified rep${rep.rep_count === 1 ? '' : 's'}`} />
            <Tile n={rep.course_count ?? courses.length} label="courses" />
            <Tile n={rep.timetable_count ?? timetable.length} label="classes" />
          </div>

          <section className="mgroup" id="m-people" aria-labelledby="m-people-h">
            <header className="mgroup__head">
              <p className="eyebrow-label">People</p>
              <h2 className="mgroup__title" id="m-people-h">Who is in your community</h2>
              <p className="mgroup__lede">
                Requests to join wait here until you decide. Reps are elected by the
                community itself.
              </p>
            </header>
            <div className="mgroup__grid">
              {/* First, because it blocks other people. */}
              <Board title="Awaiting your decision" icon={IconUser}>
                {rep.pending_requests.length === 0 ? (
                  <EmptyState title="Nobody is waiting for approval"
                              message="A student who requests to join this community appears here
                                       until you approve or reject them." />
                ) : rep.pending_requests.map((request) => (
                  <Row key={request.user_id} when={whenParts(request.requested_at)}
                       title={request.full_name}
                       meta="Requested to join"
                       side={<>
                         {/* C·11 — a decision pair. Presenting Reject as the quiet
                             option would bias a governance decision, so both carry
                             equal weight, with Reject outlined. */}
                         <button type="button" className="btn btn--primary"
                                 onClick={() => respond(request.user_id, 'approve')}>Approve</button>
                         <button type="button" className="btn btn--danger"
                                 onClick={() => respond(request.user_id, 'reject')}>Reject</button>
                       </>} />
                ))}
              </Board>
              <Board title="Rep management" icon={IconShield}
                     action={<Link className="linkish" to="/community/elections">Open Elections</Link>}>
                {candidates.length === 0 ? (
                  <EmptyState title="No nominations yet"
                              message="Any member of this community can stand for election." />
                ) : candidates.map((candidate) => (
                  <Row key={candidate.id} title={candidate.full_name}
                       meta={candidate.status === 'OPEN' && candidate.closes_at
                         ? `Closes ${longDate(candidate.closes_at)}`
                           + ` at ${candidate.closes_at.slice(11, 16)}`
                         : null}
                       side={<StateChip value={candidate.status} context="ballot" />} />
                ))}
              </Board>
            </div>
          </section>

          <section className="mgroup" id="m-records" aria-labelledby="m-records-h">
            <header className="mgroup__head">
              <p className="eyebrow-label">Academic records</p>
              <h2 className="mgroup__title" id="m-records-h">Courses, classes and the session</h2>
              <p className="mgroup__lede">
                The structure everything else is dated against. Students enrol in
                courses themselves; classes repeat every week.
              </p>
            </header>
            <div className="mgroup__grid">
              <CourseManager courses={courses} onChanged={resource.reload} setError={setError} />
              <TimetableManager timetable={timetable} courses={courses}
                                onChanged={resource.reload} setError={setError} />
            </div>
            {/* Last: uploaded once a session. */}
            <Panel title="Academic calendar">
              <p className="t-meta">
                {calendar
                  ? `The session runs from ${spokenDay(calendar.session_start) ?? 'an unknown date'} `
                    + `to ${spokenDay(calendar.session_end) ?? 'an unknown date'}. `
                    + `${calendar.periods.length} date${calendar.periods.length === 1 ? '' : 's'} `
                    + `${calendar.periods.length === 1 ? 'was' : 'were'} found in it.`
                  : 'No academic calendar uploaded yet.'}
              </p>
              <div style={{ marginTop: 'var(--s4)' }}>
              <AddForm label="Replace the academic calendar" always={!calendar}>
              <form className="stack" onSubmit={uploadCalendar}>
                {/* The shared Field, so this box looks and behaves like every other
                    text control rather than a bare browser textarea. */}
                <Field id="cal" label="Paste the academic calendar" required>
                  {(props) => <textarea {...props} name="raw_text" required rows={5} />}
                </Field>
                <button type="submit" className="btn btn--secondary"
                        style={{ alignSelf: 'flex-start' }}>Upload calendar</button>
              </form>
              </AddForm>
              </div>
            </Panel>
          </section>

          <section className="mgroup" id="m-comms" aria-labelledby="m-comms-h">
            <header className="mgroup__head">
              <p className="eyebrow-label">Communication</p>
              <h2 className="mgroup__title" id="m-comms-h">What you tell the community</h2>
              <p className="mgroup__lede">
                An announcement goes to every member and is attributed to you.
              </p>
            </header>
            <Board title="Announcements" icon={IconMegaphone}
                   foot={<AddForm label="New announcement"><form className="stack" onSubmit={announce}>
                     <Field id="a-title" label="Title" name="title" required />
                     <Field id="a-body" label="Message" required>
                       {(props) => <textarea {...props} name="body" required rows={3} />}
                     </Field>
                     <button type="submit" className="btn btn--secondary"
                             style={{ alignSelf: 'flex-start' }}>Publish announcement</button>
                   </form></AddForm>}>
              {(announcements ?? []).length === 0 ? (
                <EmptyState title="Nothing published yet"
                            message="An announcement goes to every member of this community and
                                     is attributed to you." />
              ) : (
                <div data-testid="announcement-manage-list">
                  {(announcements ?? []).map((item) => (
                    <div className="brow brow--flat" key={item.id}>
                      {editingAnnouncement === item.id ? (
                        <form className="stack" style={{ width: '100%' }}
                              onSubmit={(e) => saveAnnouncement(e, item)}>
                          <Field id={`an-title-${item.id}`} label="Title" name="title" required
                                 defaultValue={item.title} />
                          <Field id={`an-body-${item.id}`} label="Message" required>
                            {(props) => (
                              <textarea {...props} name="body" required rows={2}
                                        defaultValue={item.body} />
                            )}
                          </Field>
                          <div className="row-x stackable">
                            <button type="submit" className="btn btn--primary">Save announcement</button>
                            <button type="button" className="btn btn--secondary"
                                    onClick={() => setEditingAnnouncement(null)}>Cancel editing</button>
                          </div>
                        </form>
                      ) : (
                        <>
                          <div className="brow__main">
                            <div className="brow__title">{item.title}</div>
                            {/* Prose a person wrote, in the UI face. */}
                            <div className="brow__meta">
                              <span className="prose">{item.body}</span>
                            </div>
                          </div>
                          <div className="brow__side">
                            <StatusBadge value={item.status} />
                            {item.status === 'PUBLISHED' && (
                              <>
                                <button type="button" className="btn btn--secondary"
                                        data-testid={`edit-announcement-${item.id}`}
                                        onClick={() => setEditingAnnouncement(item.id)}>Edit</button>
                                <button type="button" className="btn btn--danger"
                                        data-testid={`withdraw-announcement-${item.id}`}
                                        onClick={() => withdrawAnnouncement(item)}>Withdraw</button>
                              </>
                            )}
                          </div>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </Board>
          </section>
        </div>
      </div>
    </div>
  );
}
