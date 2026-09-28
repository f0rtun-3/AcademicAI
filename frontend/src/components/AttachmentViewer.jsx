// Reading the original brief without leaving AcademicAI.
//
// WHY THE BYTES COME THROUGH FETCH
// --------------------------------
// Every request to this API carries a bearer token, and `<img src>` or
// `<iframe src>` cannot send one. So the file is fetched, turned into a
// `blob:` URL, and that URL is what the preview element points at. The object
// URL is revoked when the dialog closes, so nothing outlives the view.
//
// WHAT IS SAFE TO RENDER
// ----------------------
// Only formats the browser can display on its own, and only formats the
// upload allow-list already restricts us to. Crucially that list contains no
// HTML and no SVG: a `blob:` URL inherits this page's origin, so a stored
// document that could carry markup and script would be a real cross-site
// scripting route. Images, PDFs and plain text cannot be.
//
// THE PDF FRAME CARRIES NO `sandbox`, DELIBERATELY
// ------------------------------------------------
// I tried. Measured in a real browser: with `sandbox` set to any value -
// `allow-same-origin`, `allow-scripts`, or empty - the frame's document is
// opaque and Chrome's PDF viewer never loads, leaving a broken-document icon.
// Only with the attribute absent does the frame report
// `contentType: application/pdf`. A sandbox that silently breaks the feature
// is not security, it is a blank box.
//
// What makes the absence acceptable is the upload allow-list, not optimism. A
// `blob:` URL inherits this origin, so the question is whether a stored file
// could contain markup or script. It cannot: the accepted formats include no
// HTML and no SVG, and every upload is checked against its magic bytes
// server-side, so a `.pdf` full of `<script>` is refused at the door. A PDF's
// own JavaScript runs in the browser's separate viewer process and cannot
// reach this document, its storage, or the session token.
//
// The blob is also re-typed from OUR validated content_type below rather than
// from the response header, so the iframe can only ever be handed something
// the database already agreed was a PDF.
//
// WHAT IS NOT PREVIEWED
// ---------------------
// Word, PowerPoint and HEIC. No browser renders them without a converter, and
// converting documents server-side is a document-management system, which
// this deliberately is not. Those say so plainly and offer the download,
// rather than opening an empty frame and letting the reader wonder.

import { useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { errorText } from './States.jsx';
import { Modal, Notice } from './ui.jsx';

const IMAGE = new Set(['image/png', 'image/jpeg', 'image/webp']);

export function canPreview(contentType) {
  return IMAGE.has(contentType)
      || contentType === 'application/pdf'
      || contentType === 'text/plain';
}

// Said in the reader's terms: what it is, not which MIME type we refused.
const NO_PREVIEW = {
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'Word documents',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PowerPoint files',
  'application/msword': 'Word documents',
  'image/heic': 'HEIC photos',
};

export default function AttachmentViewer({ file, path, onClose, leaving = false }) {
  const [state, setState] = useState({ status: 'loading' });

  useEffect(() => {
    let url = null;
    let cancelled = false;
    if (!canPreview(file.content_type)) {
      setState({ status: 'unsupported' });
      return undefined;
    }
    (async () => {
      try {
        const blob = await api.fetchBlob(path);
        if (cancelled) return;
        if (file.content_type === 'text/plain') {
          setState({ status: 'text', text: await blob.text() });
          return;
        }
        // Re-typed from the stored, validated content type. `response.blob()`
        // takes its type from a header; this takes it from the column the
        // server wrote after sniffing the bytes.
        url = URL.createObjectURL(new Blob([blob], { type: file.content_type }));
        setState({ status: 'ready', url });
      } catch (error) {
        if (!cancelled) setState({ status: 'error', error });
      }
    })();
    return () => {
      cancelled = true;
      // The preview must not outlive the dialog that showed it.
      if (url) URL.revokeObjectURL(url);
    };
  }, [file.content_type, path]);

  return (
    <Modal title={file.filename} onClose={onClose} leaving={leaving}
           className="modal--viewer"
           actions={<>
             <button type="button" className="btn btn--secondary" onClick={onClose}>
               Close
             </button>
             <button type="button" className="btn btn--primary"
                     onClick={() => api.download(path, file.filename)}>
               Download
             </button>
           </>}>
      <div className="viewer">
        {state.status === 'loading' && (
          <p className="prose" role="status">Opening {file.filename}…</p>
        )}

        {state.status === 'error' && (
          <Notice tone="crit" label="Could not open it" role="alert">
            {errorText(state.error, 'read')} You can still download it.
          </Notice>
        )}

        {state.status === 'unsupported' && (
          <Notice tone="info" label="No preview for this format">
            {NO_PREVIEW[file.content_type] ?? 'Files of this type'} cannot be shown
            in a browser. Download it to open it in the app that reads it.
          </Notice>
        )}

        {state.status === 'text' && <pre className="viewer__text">{state.text}</pre>}

        {state.status === 'ready' && IMAGE.has(file.content_type) && (
          // The filename is the only description we have; it is usually the
          // real one the lecturer gave, which is better than "attachment".
          <img className="viewer__img" src={state.url} alt={file.filename} />
        )}

        {state.status === 'ready' && file.content_type === 'application/pdf' && (
          <iframe className="viewer__pdf" src={state.url} title={file.filename} />
        )}
      </div>
    </Modal>
  );
}
