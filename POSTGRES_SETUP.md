# PostgreSQL Setup Guide

**Goal:** Get PostgreSQL installed and running on your computer, and create
an empty database called `mlb_betting_edge`.

This guide does **not** create any tables yet. Once the empty database
exists, that's a separate step we'll confirm together first (per
`CLAUDE.md` rule 6 — confirm before touching the database).

---

## 1. What Is PostgreSQL? (Beginner Explanation)

So far, this project's "database" has only existed as a text file —
`database/schema.sql` — describing what tables *should* look like. That
file is a **blueprint**. PostgreSQL is the actual **building**.

**PostgreSQL** is a free program that runs quietly in the background on
your computer, like a filing cabinet that's always open and ready. Once
it's running, our Python backend can connect to it, build the tables from
the blueprint, and start saving real data — games, odds, team records, etc.

A few terms you'll see:

- **PostgreSQL server** — the background program that stores and manages
  data. Think of it as the librarian guarding the filing cabinet.
- **psql** — a command-line tool for talking directly to PostgreSQL
  (type a command, get an answer). Useful for double-checking things.
- **pgAdmin** — a visual tool (windows, buttons, tables) for the same
  thing — comes bundled with the installer, handy for beginners.
- **Database** — one "filing cabinet" inside PostgreSQL. We'll create one
  called `mlb_betting_edge`, and everything in this project lives inside it.

---

## 2. What We Found On Your Computer

We checked, and PostgreSQL is **not installed yet**:
- `psql` is not available in the terminal
- No PostgreSQL service is running
- No PostgreSQL folder in Program Files

So the first step is installing it.

---

## 3. Installation — Step by Step (Windows)

### Step 1 — Download the installer

1. Go to: https://www.postgresql.org/download/windows/
2. Click **"Download the installer"** (this links to EnterpriseDB, the
   official Windows installer maintainer)
3. Download the latest version (PostgreSQL 17 or 16 — either works fine
   for this project)

### Step 2 — Run the installer

Open the downloaded `.exe` and click through the setup wizard. Default
options are fine for almost everything — **except** the items below.

### Step 3 — Set a password (IMPORTANT — write it down)

You'll be asked to create a password for the default database user,
called `postgres`.

**Write this password down somewhere safe.** You'll need it soon for
`backend/.env`. This is a brand new password just for your local database
— not the same as any API key.

### Step 4 — Port number

The installer suggests port `5432`. **Keep the default** — it matches what
`.env.example` already expects.

### Step 5 — Components

Make sure these stay checked (checked by default):
- PostgreSQL Server
- pgAdmin 4
- Command Line Tools (this is what gives you `psql`)

If "Stack Builder" pops up at the end, you can close/skip it — we don't
need it.

### Step 6 — Finish

Click through to finish. Installation can take a few minutes.

---

## 4. Verify the Install

Close and reopen your terminal (PowerShell), then run:

```
psql --version
```

You should see something like:

```
psql (PostgreSQL) 17.2
```

If you see "command not found," see **Troubleshooting** below.

---

## 5. Next Steps (after install succeeds)

Once `psql --version` works, let Claude know. We'll then:

1. Create the empty `mlb_betting_edge` database (no tables yet)
2. Update `backend/.env` with your real `DATABASE_URL`, using the password
   from Step 3:

   ```
   DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/mlb_betting_edge
   ```

3. **Separately**, once you confirm, run `database/schema.sql` to create
   the 5 tables (`teams`, `games`, `starting_pitchers`, `odds_history`,
   `team_records`)

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `psql: command not found` after install | Close and reopen your terminal. Still broken? See "Add to PATH manually" below. |
| Forgot your password during setup | We can reset it together via pgAdmin if needed — just let Claude know. |

### Add to PATH manually (if needed)

1. Find where PostgreSQL was installed, usually:
   `C:\Program Files\PostgreSQL\17\bin`
2. Add that folder to your Windows PATH environment variable
3. Restart your terminal and try `psql --version` again
