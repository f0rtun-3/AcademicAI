// Reading the original brief without leaving AcademicAI.
//
// The bytes come through fetch because every API request carries a bearer
// token, which `<img src>` and `<iframe src>` cannot send. The file becomes a
// `blob:` URL for the preview, revoked when the dialog closes.
//
// Only formats the browser displays natively, and that the upload allow-list
// permits, are rendered. A `blob:` URL inherits this page's origin, so the
// allow-list deliberately contains no HTML and no SVG, and the server checks
// every upload against its magic bytes: a stored file cannot carry markup or
// script into this origin.
//
// The PDF frame has no `sandbox` attribute on purpose: with any sandbox value
// Chrome's PDF viewer does not load. The allow-list is what makes that safe,
// and a PDF's own JavaScript runs in the browser's separate viewer process,
// away from this document and the session token. The blob is re-typed from
// our validated content_type below, never from the response header.
//
// Word, PowerPoint and HEIC are not previewed - no browser renders them
// without a converter - so they say so and offer the download.

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
