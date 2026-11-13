import axios from 'axios';

// VITE_API_BASE wins when set ('' = same origin). Unset: the Vite dev server talks to the local
// backend on :8000, and a production build uses its own origin (nginx proxies /api), so phones on
// the Raspberry Pi's Wi-Fi reach the Pi instead of their own localhost.
const API_BASE = import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? 'http://localhost:8000' : '');

const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    // A request cancelled on purpose (user left the page, newer search) is not an error.
    if (!axios.isCancel(err)) console.error('[API Error]', err?.response?.status, err?.message);
    return Promise.reject(err);
  }
);

export default api;
