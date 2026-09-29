import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { errorText } from '../components/States.jsx';
import { Notice } from '../components/ui.jsx';
import { spokenDay } from '../lib/vocabulary.js';
import { BrandMark } from '../components/Brand.jsx';
import ChatAnswer from '../components/ChatAnswer.jsx';
import {
  IconAlert, IconBell, IconBook, IconCalendar, IconChat, IconCheck, IconClock, IconSend,
} from '../components/icons.jsx';

// How long the thinking state stays up AT MINIMUM.
//
// This is not an artificial delay bolted onto the answer. The grounded
// provider answers from records already in memory and returns in about twenty
// milliseconds, so the pending bubble appeared and vanished inside a single
// frame — the animation was there all along and nobody could see it. A floor
// makes the state legible without lying about how long the work took.
//
// Crucially it is a FLOOR, not an addition: when a request genuinely takes
// longer — a remote model, a slow connection — nothing extra is waited at all.
// The slow case is never made slower.
const MIN_THINKING_MS = 620;

// When a suggested reminder would fire, on the university's clock: "Monday
// 12 October at 08:00". The backend has already checked the suggestion and
// states it as remind_at_local, so the words are read straight from it - no
// zone conversion happens in the browser.
function reminderWhen(suggestion) {
  const local = suggestion?.remind_at_local;
  if (!local) return null;
  const day = spokenDay(local.slice(0, 10));
  const time = local.slice(11, 16);
  return day && time ? `${day} at ${time}` : null;
}

// A glyph for a suggested question, from the words of the QUESTION (which the
// product itself supplies) - never from an answer. Presentation only.
function promptGlyph(prompt) {
  const text = prompt.toLowerCase();
  if (/deadline|due/.test(text)) return IconClock;
  if (/class|timetable|tomorrow/.test(text)) return IconCalendar;
  if (/chang|cancel|venue/.test(text)) return IconAlert;
  if (/assignment|exam|quiz|test|project/.test(text)) return IconBook;
  return IconChat;
}

function settle(startedAt) {
  const remaining = MIN_THINKING_MS - (Date.now() - startedAt);
  if (remaining <= 0) return Promise.resolve();
  return new Promise((resolve) => setTimeout(resolve, remaining));
}

export default function ChatPage() {
  const { user } = useAuth();
  const [messages, setMessages] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [question, setQuestion] = useState('');
  const [prompts, setPrompts] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [suggestion, setSuggestion] = useState(null);
  const [accepting, setAccepting] = useState(false);
  // The question that failed to send, kept so the student can try again
  // without retyping it.
  const [failed, setFailed] = useState(null);
  const endRef = useRef(null);
  const inputRef = useRef(null);

  const [loadingHistory, setLoadingHistory] = useState(true);

  useEffect(() => {
    api.get('/chat/prompts').then((data) => setPrompts(data.prompts)).catch(() => setPrompts([]));
  }, []);

  // Restore the conversation so history survives a refresh. The backend can
  // hold several conversations per user; the product describes one thread, so
  // we continue the most recently updated one rather than adding a switcher.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await api.get('/chat/history');
        const latest = (list.conversations ?? [])[0];
        if (!latest || cancelled) return;
        const thread = await api.get(`/chat/history?conversation_id=${latest.id}`);
        if (cancelled) return;
        setConversationId(thread.conversation_id ?? latest.id);
        setMessages((thread.messages ?? []).map((m) => ({
          role: m.role, content: m.content,
        })));
      } catch {
        // History is a convenience: a failure here must not stop the student
        // from asking a new question.
      } finally {
        if (!cancelled) setLoadingHistory(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // `busy` is in the dependencies as well as `messages`: the thinking
  // indicator is not a message, so without it the view scrolled to the
  // question and left the indicator below the fold — the one moment it exists
  // to be seen.
  useEffect(() => {
    // Guarded: not every environment implements scrollIntoView, and failing to
    // scroll must never break the conversation.
    const node = endRef.current;
    if (node && typeof node.scrollIntoView === 'function') {
      node.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [messages, busy]);

  async function send(text) {
    const asked = (text ?? question).trim();
    // One question at a time. The input stays enabled while an answer is on
    // its way - disabling it threw keyboard focus to the top of the page - so
    // a second submit is refused here instead.
    if (!asked || busy) return;
    setBusy(true);
    setError(null);
    setFailed(null);
    setSuggestion(null);
    // `live`: added in this visit, so it animates in (a restored history
    // does not).
    setMessages((prev) => [...prev, { role: 'user', content: asked, live: true }]);
    setQuestion('');
    const startedAt = Date.now();
    try {
      const response = await api.post('/chat', {
        question: asked,
        conversation_id: conversationId ?? undefined,
      });
      await settle(startedAt);
      setConversationId(response.conversation_id);
      setMessages((prev) => [...prev, {
        role: 'assistant', content: response.answer, live: true,
      }]);
      if (response.suggested_reminder) setSuggestion(response.suggested_reminder);
    } catch (err) {
      // The failure waits too. A refusal that appears instantly reads as
      // "the form rejected you" rather than "the assistant tried".
      await settle(startedAt);
      // Nothing was saved, so the unsent turn leaves the transcript - but the
      // student's words do not vanish with it. They go back into the box,
      // unless something new has been typed there meanwhile, and focus stays
      // where the student can press Enter to try again.
      setMessages((prev) => prev.slice(0, -1));
      setQuestion((current) => current || asked);
      setFailed(asked);
      setError(err);
      inputRef.current?.focus();
    } finally {
      setBusy(false);
    }
  }

  async function acceptReminder() {
    if (accepting) return;
    setFailed(null);
    setAccepting(true);
    try {
      // Exactly the time offered, on the university's clock.
      await api.post('/reminders', {
        title: suggestion.title,
        remind_at_local: suggestion.remind_at_local,
        event_id: suggestion.event_id ?? undefined,
      });
      // The card becomes its own confirmation, where the student is looking,
      // rather than a banner at the top of the page they would have to find.
      setSuggestion((current) => (current ? { ...current, done: true } : current));
      // The button that was pressed is gone; the conversation is where the
      // keyboard belongs next.
      inputRef.current?.focus();
    } catch (err) {
      setError(err);
    } finally {
      setAccepting(false);
    }
  }

  function sendPrompt(prompt) {
    send(prompt);
    // The chip that was pressed is about to be disabled; keep the keyboard in
    // the conversation rather than letting focus fall to the page.
    inputRef.current?.focus();
  }

  // Real state, not decoration. The scope is this session's own community;
  // the offline reading is the transport failure the API client reports as
  // status 0. Nothing here is invented to fill a green dot.
  const scope = [user?.department, user?.level && `Level ${user.level}`]
    .filter(Boolean).join(' · ') || 'Your community';
  const offline = error?.status === 0;

  return (
    <div className="chatpage">
      {/* A chat header, not a page header: compact, and carrying the one
        * thing a reader needs before trusting an answer — the SCOPE the
        * assistant can see. That scope is the session's own community, so the
        * indicator states a fact rather than decorating the page with a green
        * dot that is always on. It turns warning when the last request could
        * not reach the server, because then the dot would be a lie. */}
      <header className="chathead">
        <span className="chathead__mark" aria-hidden="true"><BrandMark size={44} radius={13} /></span>
        <div className="chathead__text">
          <p className="eyebrow-label chathead__label">Assistant</p>
          <h1 className="chathead__name">AcademicAI Assistant</h1>
          <p className="chathead__lede">
            Your academic information, in one place. It reads your community&apos;s
            records — it cannot publish, change or cancel anything.
          </p>
        </div>
        <p className={`chathead__scope${offline ? ' chathead__scope--off' : ''}`}>
          <span className="chathead__dot" aria-hidden="true" />
          {offline ? 'Cannot reach AcademicAI' : scope}
        </p>
      </header>

      {error && (
        <Notice tone="crit" role="alert"
                label={failed ? 'Your question was not sent' : undefined}>
          <div className="row-x" style={{ justifyContent: 'space-between' }}>
            <span>{errorText(error)}</span>
            <span className="row-x">
              {failed && (
                <button type="button" className="btn btn--secondary btn--sm"
                        disabled={busy} onClick={() => send(failed)}>
                  Try again
                </button>
              )}
              <button type="button" className="btn btn--quiet btn--sm"
                      onClick={() => setError(null)}>
                Dismiss
              </button>
            </span>
          </div>
        </Notice>
      )}
      {loadingHistory && <p className="prose">Loading your conversation…</p>}

      {/* The transcript IS the screen. A blank chat is the hardest place to
          start, so the prompts sit above the input rather than inside it. */}
      <div className="transcript" role="log" aria-live="polite">
        {messages.length === 0 && !loadingHistory && (
          <div className="chatstart">
            <span className="chatstart__mark" aria-hidden="true">
              <BrandMark size={44} radius={11} />
            </span>
            <h2 className="chatstart__title">How can I help?</h2>
            <p className="chatstart__lede">
              Ask about your academic records — deadlines, venues, your timetable,
              or what changed recently.
            </p>
            {/* The opening offers questions as cards, each with the glyph of
                what it asks about, so the first move is a choice rather than a
                blank box. The same prompts, through the same `send`. */}
            {prompts.length > 0 && (
              <div className="promptgrid">
                {prompts.map((prompt) => {
                  const Glyph = promptGlyph(prompt);
                  return (
                    <button key={prompt} type="button" className="promptcard"
                            disabled={busy} onClick={() => sendPrompt(prompt)}>
                      <span className="promptcard__icon" aria-hidden="true"><Glyph size={17} /></span>
                      <span className="promptcard__text">{prompt}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {messages.map((message, index) => (
          message.role === 'user' ? (
            <div className={`turn turn--user${message.live ? ' turn--live' : ''}`} key={index}>
              <div className="bubble bubble--user">{message.content}</div>
            </div>
          ) : (
            /* The assistant gets an identity: the product's own mark and its
               name, so a transcript reads as a conversation rather than as
               alternating cards. Small on purpose — this is an academic tool,
               not a character. */
            <div className={`turn turn--ai${message.live ? ' turn--live' : ''}`} key={index}>
              <span className="turn__avatar" aria-hidden="true">
                <BrandMark size={28} radius={8} />
              </span>
              <div className="turn__body">
                <p className="turn__who">AcademicAI</p>
                <div className="bubble bubble--ai">
                  <ChatAnswer content={message.content} />
                </div>
              </div>
            </div>
          )
        ))}

        {/* The pending answer takes the answer's own shape, so the transcript
            does not jump when it arrives, and so "Thinking…" reads as the
            assistant rather than as a caption on the page. */}
        {busy && (
          <div className="turn turn--ai">
            <span className="turn__avatar" aria-hidden="true">
              <BrandMark size={28} radius={8} />
            </span>
            <div className="turn__body">
              <p className="turn__who">AcademicAI</p>
              {/* Not a typing indicator: the assistant is READING the
                  community's records, and says so - a signal trace runs along
                  a rule while it works. Grounding, stated in the wait. */}
              <div className="bubble bubble--ai bubble--pending">
                <span className="trace" aria-hidden="true"><i /></span>
                <span className="trace__text">Reading your community&apos;s records…</span>
              </div>
            </div>
          </div>
        )}
        {/* A reminder is an OFFER requiring an explicit accept; nothing is
            created silently. It is an action card, not a notice - a question
            put to the student, not something that has happened - and it sits
            IN the conversation, under the answer that offered it. Placed after
            the transcript it scrolled in underneath the sticky composer, which
            covered it; inside the log it is also announced with its answer. */}
        {suggestion && (
          <section className={`suggest${suggestion.done ? ' suggest--done' : ''}`}
                   aria-label={suggestion.done ? 'Personal reminder created' : 'Suggested reminder'}>
            {/* Accepted, the same card confirms it: the tile fills and a
                check draws in, the first line says what happened, and the
                title and time stay exactly where they were (§31). */}
            <span className="suggest__icon" aria-hidden="true">
              {suggestion.done
                ? <span className="tick"><IconCheck size={18} /></span>
                : <IconBell size={18} />}
            </span>
            <div className="suggest__body">
              {suggestion.done
                ? <p className="suggest__kind suggest__done">Personal reminder created.</p>
                : <p className="suggest__kind">Suggested personal reminder</p>}
              <p className="suggest__title">{suggestion.title}</p>
              {/* When it would fire, so accepting it is an informed choice. */}
              {reminderWhen(suggestion) && (
                <p className="suggest__when">{reminderWhen(suggestion)}</p>
              )}
            </div>
            {suggestion.done ? (
              <div className="suggest__actions suggest__done">
                <Link className="linkish" to="/reminders">See your reminders</Link>
              </div>
            ) : (
              <div className="suggest__actions">
                {/* Secondary: the screen's one primary action is Ask. */}
                <button type="button" className="btn btn--secondary" onClick={acceptReminder}
                        disabled={accepting} aria-busy={accepting || undefined}>
                  Add reminder
                </button>
                <button type="button" className="btn btn--quiet" disabled={accepting}
                        onClick={() => setSuggestion(null)}>
                  No thanks
                </button>
              </div>
            )}
          </section>
        )}
        <div ref={endRef} />
      </div>

      {/* The composer.
        *
        * The input and its send action share one bordered container that
        * carries the focus ring, so the two read as one control rather than a
        * text box with a button parked beside it. The <label> is still a real
        * label — visually hidden, not removed — because the placeholder is an
        * example question and would vanish the moment someone typed.
        *
        * The chips sit ABOVE it once a conversation has started, so a follow-up
        * is one click away without the empty state's larger opening. They send
        * the same prompts the backend supplies, through the same `send`. */}
      <div className="composer">
        {messages.length > 0 && prompts.length > 0 && (
          <div className="promptchips">
            {prompts.slice(0, 4).map((prompt) => (
              <button key={prompt} type="button" className="chip-btn" disabled={busy}
                      onClick={() => sendPrompt(prompt)}>
                {prompt}
              </button>
            ))}
          </div>
        )}

        <form className="askbar" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <label className="sr-only" htmlFor="question">Your question</label>
          <div className="askbar__box">
            <input id="question" ref={inputRef} className="askbar__input" autoComplete="off"
                   placeholder="Ask about your deadlines, venues or timetable…"
                   value={question} aria-busy={busy || undefined}
                   aria-describedby="question-note"
                   onChange={(e) => setQuestion(e.target.value)} />
            <button type="submit" className="btn btn--ai askbar__send"
                    disabled={busy || !question.trim()}>
              <IconSend size={16} />
              <span className="askbar__sendword">Ask</span>
            </button>
          </div>
        </form>
        <p className="askbar__note" id="question-note">
          Answers come only from your community&apos;s academic records.
        </p>
      </div>
    </div>
  );
}
