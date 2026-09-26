import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { SuccessBanner, errorText } from '../components/States.jsx';
import { Notice, localTime } from '../components/ui.jsx';
import { spokenDay } from '../lib/vocabulary.js';
import { BrandMark } from '../components/Brand.jsx';
import ChatAnswer from '../components/ChatAnswer.jsx';
import { IconSend } from '../components/icons.jsx';

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

// When a suggested reminder would fire, in the student's own clock: "Monday
// 12 October at 09:00". The instant comes from the backend; only its wording
// is local.
function reminderWhen(instant) {
  if (!instant) return null;
  const at = new Date(instant);
  if (Number.isNaN(at.getTime())) return null;
  const pad = (n) => String(n).padStart(2, '0');
  const day = spokenDay(`${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`);
  return day ? `${day} at ${localTime(instant)}` : null;
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
  const [notice, setNotice] = useState(null);
  const [suggestion, setSuggestion] = useState(null);
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
    setMessages((prev) => [...prev, { role: 'user', content: asked }]);
    setQuestion('');
    const startedAt = Date.now();
    try {
      const response = await api.post('/chat', {
        question: asked,
        conversation_id: conversationId ?? undefined,
      });
      await settle(startedAt);
      setConversationId(response.conversation_id);
      setMessages((prev) => [...prev, { role: 'assistant', content: response.answer }]);
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
    setFailed(null);
    try {
      await api.post('/reminders', suggestion);
      setNotice('Personal reminder created.');
      setSuggestion(null);
    } catch (err) {
      setError(err);
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
        <span className="chathead__mark" aria-hidden="true"><BrandMark size={38} radius={9} /></span>
        <div className="chathead__text">
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

      <SuccessBanner message={notice} onDismiss={() => setNotice(null)} />
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
            {prompts.length > 0 && (
              <div className="promptchips promptchips--start">
                {prompts.map((prompt) => (
                  <button key={prompt} type="button" className="chip-btn"
                          disabled={busy} onClick={() => sendPrompt(prompt)}>
                    {prompt}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {messages.map((message, index) => (
          message.role === 'user' ? (
            <div className="turn turn--user" key={index}>
              <div className="bubble bubble--user">{message.content}</div>
            </div>
          ) : (
            /* The assistant gets an identity: the product's own mark and its
               name, so a transcript reads as a conversation rather than as
               alternating cards. Small on purpose — this is an academic tool,
               not a character. */
            <div className="turn turn--ai" key={index}>
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
              <div className="bubble bubble--ai bubble--pending">
                <span className="thinking" aria-hidden="true">
                  <i /><i /><i />
                </span>
                <span className="sr-only">Thinking…</span>
              </div>
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* A reminder is an OFFER requiring an explicit accept. Nothing is
          created silently. */}
      {suggestion && (
        <Notice tone="pos" label="Personal reminder">
          <div className="row-x" style={{ justifyContent: 'space-between' }}>
            <span>
              {suggestion.title}
              {/* When it would fire, so accepting it is an informed choice. */}
              {reminderWhen(suggestion.remind_at) && (
                <span className="t-meta" style={{ display: 'block' }}>
                  {reminderWhen(suggestion.remind_at)}
                </span>
              )}
            </span>
            <span className="row-x">
              <button type="button" className="btn btn--secondary" onClick={acceptReminder}>
                Add reminder
              </button>
              <button type="button" className="btn btn--quiet"
                      onClick={() => setSuggestion(null)}>
                No thanks
              </button>
            </span>
          </div>
        </Notice>
      )}

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
            <button type="submit" className="btn btn--primary askbar__send"
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
