# gametime

MLB pregame ensemble (Python CLI + API) and Next.js slate site.

Full MLB ops reference: [docs/mlb_pregame_ops.md](docs/mlb_pregame_ops.md).

## Python setup (repo root)

Python ≥3.9. Create the virtualenv **on each machine** (do not copy `.venv` between Mac and NAS).

```bash
cd gametime
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e '.[mlb,api]'
```

| Extra | Installs |
|-------|----------|
| `[mlb]` | pybaseball, download + slate CLI |
| `[api]` | FastAPI + uvicorn |

On Debian/Ubuntu (e.g. Ugreen NAS over SSH), install venv support once:

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip
```

If console scripts are missing after install:

```bash
export PYTHONPATH=src
python3 -m gametime.cli pregame-slate --config configs/mlb.yaml --date 2024-06-15 --regular-season
```

## MLB projections (CLI)

`data/` and `models/` are not in git. Copy them from another machine or seed once:

```bash
source .venv/bin/activate
gametime-download --config configs/mlb.yaml
gametime-pregame-train --config configs/mlb.yaml   # only if models/mlb/pregame/ is empty
```

**Every new shell session**, activate the venv first:

```bash
cd gametime
source .venv/bin/activate
```

Today's slate:

```bash
gametime-pregame-slate --config configs/mlb.yaml --date $(date +%Y-%m-%d) --regular-season
```

Single game:

```bash
gametime-pregame --config configs/mlb.yaml --home NYY --away BOS --regular-season
```

Daily data refresh (run before slates):

```bash
gametime-download --config configs/mlb.yaml
```

Predictions API (same ensemble as CLI):

```bash
uvicorn gametime.api.app:app --reload
# or: docker compose up -d api
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
```

---

## Web app (`web/`)

### Setup

```bash
cd web
npm install
```

### Development

Run the Python predictions API and the Next.js dev server in separate terminals:

```bash
# Terminal 1 — API (repo root, venv active)
source .venv/bin/activate
uvicorn gametime.api.app:app --reload

# Terminal 2 — web
cd web
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Try a historical date, e.g. [/?date=2024-06-15](http://localhost:3000/?date=2024-06-15).

The browser calls same-origin **`/api/health`**, **`/api/slate`**, and **`/api/game`** route handlers; those proxies fetch the Python API server-side (no CORS setup required in the browser).

### Production build

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

Deploy steps: [docs/deploy-local-tunnel.md](docs/deploy-local-tunnel.md) (recommended) or [docs/deploy.md](docs/deploy.md) (Fly alternate).

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
