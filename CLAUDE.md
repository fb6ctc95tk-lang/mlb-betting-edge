# CLAUDE.md — Instructions for Claude Code

## Project
MLB Betting Edge — a personal sports betting research dashboard.

## User
Beginner developer. Explain things step by step. Never overengineer.
Build one working piece at a time. Always save work to files.

## Tech Stack
- Database: PostgreSQL
- Backend: Python + FastAPI
- Frontend: Next.js (React)
- Data: SportsDataIO API
- Future hosting: Supabase + Railway + Vercel

## Rules for Claude

1. **Always explain what you're building before building it.**
2. **One feature at a time** — finish it, test it, then move on.
3. **No unnecessary abstractions.** Keep code simple and readable.
4. **No comments that explain what the code does** — only comments for non-obvious WHY.
5. **Always write to files** — never leave important work only in the chat.
6. **Before touching the database**, confirm the schema change with the user.
7. **When something could break data**, warn the user first.

## Project Structure

```
mlb-betting-edge/
├── backend/      # Python FastAPI server + data fetching scripts
├── frontend/     # Next.js web dashboard
├── database/     # SQL schema and migration files
├── docs/         # Notes, API references, research
```

## Current Phase
Phase 1 — Foundation. See PROJECT_PLAN.md for full roadmap.
