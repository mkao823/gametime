# gametime web

Next.js app for the public MLB slate site (TASK-23+).

## Setup

```bash
cd web
npm install
```

## Development

Run the Python predictions API and the Next.js dev server in separate terminals:

```bash
# Terminal 1 — API (repo root)
pip install -e '.[api]'
uvicorn gametime.api.app:app --reload

# Terminal 2 — web
cd web
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Try a historical date, e.g. [/?date=2024-06-15](http://localhost:3000/?date=2024-06-15).

The browser calls same-origin **`/api/health`**, **`/api/slate`**, and **`/api/game`** route handlers; those proxies fetch the Python API server-side (no CORS setup required in the browser).

## Production build

```bash
npm run build
npm start
```

## API configuration

| Variable | Used by | Default |
|----------|---------|---------|
| `GAMETIME_API_URL` | Server-side proxy (`app/api/*`) | `http://127.0.0.1:8000` |
| `NEXT_PUBLIC_API_URL` | Fallback if `GAMETIME_API_URL` unset | `http://127.0.0.1:8000` |

**Local dev:** leave both unset (defaults to `http://127.0.0.1:8000`) or set `GAMETIME_API_URL=http://127.0.0.1:8000`.

**Vercel production (local API + Cloudflare Tunnel):** set only **`GAMETIME_API_URL`** to your tunnel HTTPS URL, e.g. `https://api.example.com` (named tunnel) or `https://<random>.trycloudflare.com` (quick tunnel for dev smoke). Do not point `NEXT_PUBLIC_API_URL` at the tunnel — the browser uses same-origin `/api/health` and `/api/slate` only.

**Vercel production (Fly.io alternate):** `GAMETIME_API_URL=https://gametime-api.fly.dev`.

Deploy steps: [docs/deploy-local-tunnel.md](../docs/deploy-local-tunnel.md) (recommended) or [docs/deploy.md](../docs/deploy.md) (Fly alternate).

## Routes

| Route | Description |
|-------|-------------|
| `/` | Daily slate with date picker and game cards |
| `/mlb` | Redirects to `/` |
| `/methodology` | Methodology markdown |
| `/disclaimer` | Legal disclaimer |
| `/about` | About page |
| `/mlb/game?home=&away=&date=` | Game detail with predicted scoreline and member breakdown |
| `/api/game` | BFF proxy to `GET /v1/game` (`include_members=true`) |

## Content

Markdown pages load from `content/` at build time. See `content/README.md` for frontmatter conventions.
