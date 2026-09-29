// Single place that talks to the Flask API.
//
// The token lives in memory plus localStorage; every request carries it as a
// bearer header. A 401 clears the session so the app falls back to login
// rather than showing a half-authenticated screen.

import { announce, REMINDERS_CHANGED } from '../lib/liveEvents.js';
import { PASSWORD_RESET_AVAILABLE, PASSWORD_RESET_PATHS } from '../lib/features.js';

const BASE_URL = import.meta.env?.VITE_API_URL ?? '';
const TOKEN_KEY = 'academicai.token';

// `undefined` means "not read from storage yet". Reading lazily rather than at
// module load means a token stored after this module is imported is still seen.
let token;

function readStoredToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

const listeners = new Set();

export function onUnauthorized(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function getToken() {
  if (token === undefined) token = readStoredToken();
  return token;
}

export function setToken(value) {
  token = value;
  try {
    if (value) localStorage.setItem(TOKEN_KEY, value);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode); the in-memory token still works */
  }
}

export class ApiError extends Error {
  constructor(status, payload) {
    super(payload?.message || 'Something went wrong.');
    this.status = status;
    this.code = payload?.error;
    this.details = payload?.details || {};
    // Whether the BACKEND actually wrote a sentence for this, as opposed to
    // the fallback above. The UI keeps a real backend sentence even on a
    // framed status, and only supplies its own words when there are none.
    this.serverMessage = typeof payload?.message === 'string' && payload.message
      ? payload.message
      : null;
  }
}

async function request(method, path, body) {
  // Switched-off features cannot be reached from any screen: the request is
  // refused here, before anything leaves the browser (lib/features.js).
  if (!PASSWORD_RESET_AVAILABLE && PASSWORD_RESET_PATHS.has(path)) {
    throw new ApiError(503, { error: 'unavailable', message: 'Password reset is not available yet.' });
  }
  // FormData carries its own multipart boundary, so the Content-Type header
  // must be left off entirely for the browser to set it correctly.
  const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;
  const headers = isFormData ? {} : { 'Content-Type': 'application/json' };
  const bearer = getToken();
  if (bearer) headers.Authorization = `Bearer ${bearer}`;

  let requestBody;
  if (body === undefined) requestBody = undefined;
  else if (isFormData) requestBody = body;
  else requestBody = JSON.stringify(body);

  let response;
  try {
    response = await fetch(`${BASE_URL}/api${path}`, {
      method,
      headers,
      body: requestBody,
    });
  } catch {
    throw new ApiError(0, { message: 'Cannot reach the server. Check your connection.' });
  }

  if (response.status === 204) return null;

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    if (response.status === 401) {
      setToken(null);
      listeners.forEach((fn) => fn());
    }
    throw new ApiError(response.status, payload);
  }
  // Every reminder write, from whichever screen made it (the reminders page,
  // an event, a chat suggestion), tells the bell - which then learns when the
  // new next reminder is due. One place, so no caller can forget.
  if (method !== 'GET' && /^\/reminders(\/|\?|$)/.test(path)) announce(REMINDERS_CHANGED);
  return payload;
}

// Fetch a file's bytes as a Blob, for previewing in the page. Separate from
// `download` because viewing and saving are now two different actions and a
// viewer needs the bytes in hand, not a save dialog.
async function fetchBlob(path) {
  const headers = {};
  const bearer = getToken();
  if (bearer) headers.Authorization = `Bearer ${bearer}`;
  let response;
  try {
    response = await fetch(`${BASE_URL}/api${path}`, { headers });
  } catch {
    throw new ApiError(0, { message: 'Cannot reach the server. Check your connection.' });
  }
  if (!response.ok) {
    if (response.status === 401) {
      setToken(null);
      listeners.forEach((fn) => fn());
    }
    let payload = null;
    try { payload = await response.json(); } catch { payload = null; }
    throw new ApiError(response.status, payload);
  }
  return response.blob();
}

// A file download, not a JSON call. It goes through fetch rather than a plain
// <a href> because every request to this API carries a bearer token, and a
// link cannot. The blob is handed to the browser as a save, so nothing is
// rendered in the application's origin.
async function download(path, fallbackName) {
  const headers = {};
  const bearer = getToken();
  if (bearer) headers.Authorization = `Bearer ${bearer}`;
  let response;
  try {
    response = await fetch(`${BASE_URL}/api${path}`, { headers });
  } catch {
    throw new ApiError(0, { message: 'Cannot reach the server. Check your connection.' });
  }
  if (!response.ok) {
    if (response.status === 401) {
      setToken(null);
      listeners.forEach((fn) => fn());
    }
    let payload = null;
    try { payload = await response.json(); } catch { payload = null; }
    throw new ApiError(response.status, payload);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fallbackName || 'attachment';
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoked on the next tick: Safari needs the object URL to survive the click.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export const api = {
  get: (path) => request('GET', path),
  download,
  fetchBlob,
  post: (path, body = {}) => request('POST', path, body),
  // Multipart upload. `body` must be a FormData.
  postForm: (path, formData) => request('POST', path, formData),
  put: (path, body = {}) => request('PUT', path, body),
  del: (path) => request('DELETE', path),
};
