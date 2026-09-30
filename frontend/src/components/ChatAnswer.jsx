// Rendering an assistant answer.
//
// It presents the answer's OWN structure - a lead sentence, and lines that
// begin "- " become a list - and renders every character the backend sent, in
// order. It never interprets the content (icons, headings, reformatted dates):
// the wording belongs to the configured AI provider and differs between
// providers, and a mis-read line would show a student something the backend
// never said. The one exception is exact string equality - see `collapse`.

const BULLET = /^\s*[-•]\s+/;

// Consecutive IDENTICAL lines become one row with a count. This is the
// "three identical membership-approved entries" case: the information is
// preserved exactly (the same line, and how many times it appeared), and no
// judgement is made about what the line means. Only characters are compared.
function collapse(lines) {
  const out = [];
  for (const line of lines) {
    const last = out[out.length - 1];
    if (last && last.text === line) last.count += 1;
    else out.push({ text: line, count: 1 });
  }
  return out;
}

// Split the answer into runs of prose and runs of list items, preserving
// order. A blank line is a separator the provider chose; it is kept as one.
function blocks(content) {
  const result = [];
  for (const raw of String(content ?? '').split('\n')) {
    const isItem = BULLET.test(raw);
    const text = isItem ? raw.replace(BULLET, '') : raw.trim();
    const kind = isItem ? 'list' : 'prose';
    const last = result[result.length - 1];
    if (last && last.kind === kind) last.lines.push(text);
    else result.push({ kind, lines: [text] });
  }
  return result;
}

export default function ChatAnswer({ content }) {
  return (
    <div className="answer">
      {blocks(content).map((block, i) => (
        block.kind === 'list' ? (
          <ul className="answer__list" key={i}>
            {collapse(block.lines).map((item, j) => (
              <li className="answer__item" key={j}>
                {/* No marker ELEMENT. The bullet is drawn by CSS as
                    `.answer__item::before`, which means it cannot appear in
                    `textContent`, in `innerText`, in a selection, in a copy,
                    or in anything that serialises the DOM — the whole class of
                    "icon markup showed up in the text" bug, removed rather
                    than patched.

                    It is also not a per-type icon: choosing a glyph would mean
                    reading the line, which this component is not allowed to do
                    (see the note at the top of the file). */}
                <span className="answer__text">{item.text}</span>
                {item.count > 1 && (
                  // Says how many identical entries there were rather than
                  // hiding the repeats or inventing a summary for them.
                  <span className="answer__count mono"
                        aria-label={`${item.count} identical entries`}>
                    ×{item.count}
                  </span>
                )}
              </li>
            ))}
          </ul>
        ) : (
          block.lines.map((line, j) => (
            line
              ? <p className="answer__p" key={`${i}-${j}`}>{line}</p>
              // A blank line the provider wrote is a paragraph break it chose.
              : <span className="answer__gap" key={`${i}-${j}`} aria-hidden="true" />
          ))
        )
      ))}
    </div>
  );
}
