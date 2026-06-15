# Frontend

This folder contains the web dashboard the user sees in their browser.

## What Lives Here

- **Next.js app** — the visual dashboard
- **Pages** — currently just the homepage (today's games). More pages
  (matchups, props, line movement, parlay builder) will be added later.

## Technology

- Next.js 16 (App Router, React 19)
- TypeScript
- ESLint
- Plain CSS (no Tailwind yet)

## Folder Structure

```
frontend/
├── app/
│   ├── page.tsx        # Homepage — today's games table
│   ├── layout.tsx      # Root layout (page title, fonts)
│   └── globals.css     # Global styles
├── public/             # Static assets (images, icons)
├── package.json        # Node.js package list
└── .env.local          # Environment variables (API URL) — not committed
```

## Environment Variables

`.env.local` (not committed to git):

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## How to Run

```bash
cd frontend
npm install
npm run dev
```

Dashboard will be available at: http://localhost:3000

The FastAPI backend must also be running on port 8000 (see
`backend/README.md`) — the homepage fetches `/games/today` from it.
