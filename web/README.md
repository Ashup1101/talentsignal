# TalentSignal web app

The frontend of TalentSignal: Next.js (App Router, TypeScript) with Tailwind CSS,
shadcn/ui (Base UI), Recharts and Lucide icons. It is built as a **static export**
(`out/`): nginx serves the files and proxies `/api/` to the FastAPI service
(`src/api/`). There is no Node.js server in production.

## Run it locally

```bash
infra/api/run_local.sh          # from the repo root: the API on http://localhost:8000
cd web && npm install           # once
npm run dev                     # http://localhost:3000 (calls the API via .env.development)
```

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Dev server on 127.0.0.1:3000 |
| `npm run build` | Static export to `out/` |
| `npm run lint` / `npm run typecheck` | ESLint / TypeScript |
| `npm test` | Vitest + Testing Library (happy-dom) |
| `npm run gen:api` | Regenerate `src/lib/api-types.ts` from `openapi.json` |

After changing an API endpoint or `src/api/schemas.py`, run
`python -m src.api.export_openapi` (repo root) and then `npm run gen:api`; CI fails
while either is out of date.

## Layout

- `src/app/` — one folder per page: `/`, `/analyze/`, `/salaries/`, `/skills/`, `/insights/`
- `src/components/` — page views and shared pieces; `ui/` holds the shadcn components
- `src/lib/` — `api.ts` (typed client), `format.ts` (wording and rounding), `use-api.ts`
- `public/sample-resume.pdf` — a made-up resume for "Try a sample resume"

Resumes are sent as the raw PDF body to `POST /api/analyze`, analyzed in memory and
never stored.
