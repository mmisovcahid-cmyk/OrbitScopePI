import axios from 'axios';

// Unset -> local dev backend. Set to '' (e.g. the Docker/nginx build) -> same origin, /api is proxied.
const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000';

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
