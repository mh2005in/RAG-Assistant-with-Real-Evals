/**
 * Base URL for the RAG backend API.
 *
 * Empty string → same-origin requests (e.g. POST /process). In development the
 * Angular dev server proxies those paths to the backend on :8000 (see
 * proxy.conf.json), so no CORS setup is needed. In production, serve this app
 * behind a reverse proxy that forwards the same paths to the backend, or set
 * this to the backend's absolute origin (e.g. 'http://localhost:8000').
 */
export const API_BASE = '';
