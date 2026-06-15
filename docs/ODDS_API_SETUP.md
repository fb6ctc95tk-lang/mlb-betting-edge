# OddsAPI.io Setup Guide (Step 3 Verification)

**Goal:** Prove OddsAPI.io works for MLB moneyline odds before we build
anything permanent. No database writes, no fetcher, no schema changes yet —
this is a connection test only.

---

## 1. Create a Free Account

1. Go to **https://odds-api.io**
2. Click **"Get Started Free"** (top right or homepage button)
3. Sign up with your email (or Google, if offered)
4. Verify your email if asked
5. You'll land on your **Dashboard**

The free plan includes:
- **100 requests per hour**
- **2 sportsbooks** (which two, we'll find out when we run the test)
- All sports including MLB
- Moneyline, spreads, and totals markets
- No credit card required, no expiration

---

## 2. Find Your API Key

1. From the Dashboard, look for a section called **"API Keys"** or
   **"Settings"** (exact wording may vary slightly)
2. Your key will be a long string of letters and numbers, something like:

```
oa_live_a1b2c3d4e5f6g7h8i9j0
```

3. Copy this key — you'll paste it into `backend/.env` in the next step

If you can't find it on the dashboard, check your email — some providers
send the key in your welcome email instead.

---

## 3. How the API Key Works

Every request to OddsAPI.io includes your key as part of the URL, like this:

```
https://api.odds-api.io/v3/events?apiKey=YOUR_KEY_HERE&sport=mlb
```

Think of it the same way as the SportsDataIO key from `SETUP_GUIDE.md` —
it's your membership card. The difference is *where* it goes: SportsDataIO
also used a `key=` parameter, and OddsAPI.io uses `apiKey=`. Same idea,
slightly different name.

---

## 4. Where the Key Will Be Stored

Same pattern as before — **never written in code**.

```
mlb-betting-edge/
├── backend/
│   └── .env          ← ODDS_API_KEY goes here (private, never shared)
├── .env.example       ← template, already updated with ODDS_API_KEY
```

If you don't have `backend/.env` yet:

```
cd backend
copy ..\.env.example .env
```

Then open `backend/.env` and set:

```
ODDS_API_KEY=paste_your_real_key_here
```

`.gitignore` already blocks `.env` from ever being committed — nothing
extra to set up there.

---

## 5. Free Tier Limits — What to Expect

| Limit | Value |
|---|---|
| Requests per hour | 100 |
| Sportsbooks included | 2 (we'll see which ones in the test output) |
| Cost | $0, no credit card |
| Expiration | None — free forever |
| Markets | Moneyline (called "ML"), spreads, totals |

**Why this matters for our project:** one API call returns odds for *one*
game from *one* set of bookmakers. To avoid burning through 100 requests/hour
during testing, our test script only checks the **first 3 games** of the day.

When we build the real fetcher later (Step 4), checking all ~15 games
every 15-30 minutes for line movement would use roughly 30-60 requests/hour —
comfortably within the free limit.

---

## 6. A Note on Odds Format

OddsAPI.io returns moneylines as **decimal odds** (e.g. `2.10`), which is
the international standard. Our database (`odds_history` table) stores
**American odds** (e.g. `+110`, `-140`), which is the U.S. standard.

The test script converts decimal → American just for display, so the
numbers look familiar. This conversion will become a real (small) function
in the fetcher we build in Step 4.

Quick reference:
- Decimal `2.10` = American `+110` (underdog)
- Decimal `1.85` = American `-118` (favorite)

---

## 7. Running the Test

```
cd backend
python test_odds_api.py
```

**Success looks like:** sportsbook names, team names, and moneyline odds
printed in the terminal for a few of today's MLB games.

If something doesn't match (e.g., the response shape is different than
expected), the script prints the raw response so we can adjust together —
this is normal for a first connection test with a new provider.
