# gametime web

Next.js app for the public MLB slate site (TASK-23+).

## Setup

```bash
cd web
npm install
```

## Development

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Production build

```bash
npm run build
npm start
```

## API configuration

TASK-24+ fetches predictions from the Python API. Set the base URL via environment variable:

```bash
export NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

Default (when unset): `http://127.0.0.1:8000` — see `lib/config.ts`.

Start the API locally:

```bash
pip install -e '.[api]'
uvicorn gametime.api.app:app --reload
```

## Routes (TASK-23)

| Route | Description |
|-------|-------------|
| `/` | Daily slate (placeholder until TASK-24) |
| `/mlb` | Redirects to `/` |
| `/methodology` | Methodology markdown |
| `/disclaimer` | Legal disclaimer |
| `/about` | About page |
| `/mlb/game` | Game detail stub (TASK-25) |

## Content

Markdown pages load from `content/` at build time. See `content/README.md` for frontmatter conventions.
