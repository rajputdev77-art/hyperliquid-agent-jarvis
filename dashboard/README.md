# jarvis dashboard

Minimal Next.js 14 dashboard that polls the FastAPI backend every 10s.

## Dev

```bash
cd dashboard
cp .env.example .env.local
npm install
npm run dev
# http://localhost:3000
```

`NEXT_PUBLIC_API_URL` must point to your backend (default `http://localhost:8000`).

## Deploy to Vercel

1. `gh repo create jarvis-dashboard --public` (or create via web).
2. `git init && git add -A && git commit -m init && git push`.
3. In Vercel → Import Project → pick the repo → framework auto-detects Next.js.
4. Project Settings → Environment Variables:
   - `NEXT_PUBLIC_API_URL` = your backend URL (must be HTTPS if the Vercel site is HTTPS).
5. Deploy.

See `DEPLOY.md` in the project root for the full end-to-end deployment path including HTTPS for the backend.
