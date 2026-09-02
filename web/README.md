# reachstore web

React + Vite frontend for reachstore's reader UI.

In development, `vite.config.js` proxies `/api` to the FastAPI backend on
`http://127.0.0.1:8000`, so the browser stays same-origin — no CORS setup
needed.

## Run

```bash
npm install
npm run dev       # http://localhost:5173, backend must be running on :8000
npm run build     # production build to dist/
```
