# Odds Provider Research (Step 3)

**Date:** 2026-06-10
**Status:** Research only. No code, schema, or fetchers changed.

---

## Why We Need This

The free MLB Stats API (already working in `backend/fetchers/mlb_stats_api.py`)
gives us games, starting pitchers, and team records — but it has **no betting
odds**. Official MLB data never includes odds, because odds come from
sportsbooks, not the league.

We need a new provider for:
- Current moneyline odds (home/away)
- The ability to check odds repeatedly throughout the day, so we can build
  our own `odds_history` table (line movement)

---

## How to Read This Document

For each provider, "Line Movement Support" does **not** mean "the provider
hands us a pre-built line movement chart." It means: *can we call this API
often enough, for free or cheaply, to build line movement ourselves?*
That's how `odds_history` is designed to work — we take our own snapshots.

"Historical Odds Support" is a separate thing: data the provider already
collected *before* we started using them. Nice for backtesting later, not
required for Version 1.

---

## Comparison Table

| Criteria | The Odds API | OddsAPI.io | SportsDataIO Odds | SharpAPI |
|---|---|---|---|---|
| **Cost** | Free (limited) → $30/mo (20K credits) → $59 → $119 → $249 | Free forever (100 req/hr) → paid for 5,000+ req/hr | Opaque/sales-based. "Discovery Lab" tier reportedly ~$99–$149/mo | Free forever (12 req/min) → paid "Hobby+" for real-time + more books |
| **Free Tier Availability** | Yes, but very thin — 500 *credits*/month, and each odds call costs ~6 credits (~80 calls/month total) | Yes — 100 requests/hour (2,400/day), no card, no expiry | Free trial only — capped, next-day delayed/scrambled data, not production-grade | Yes — ~17,280 requests/day, no card, but 60-second data delay |
| **MLB Coverage** | Good — moneyline (h2h), run line, totals from ~40 US sportsbooks | Strong — moneyline, run line, totals, props from 265+ books incl. sharp books (Pinnacle) | Excellent — pre-match, in-play, props, futures, closing lines | Good — moneyline + other markets, but free tier limited to 2 sportsbooks |
| **Moneyline Support** | Yes, included on every tier including free | Yes, included on free tier | Yes, comprehensive | Yes, included on free tier |
| **Historical Odds Support** | Paid plans only. Full MLB archive from mid-2020 (included free of extra cost on the $99/mo Business tier) | Reportedly available from mid-2020, but tier/cost unclear — needs verification before relying on it | Yes — explicit historical and closing-line endpoints | Enterprise only — not available on free or low tiers |
| **Line Movement Support (via polling)** | Free tier too thin (~2-3 calls/day total). Paid $30/mo tier gives ~110 calls/day — comfortable for hourly snapshots | Free tier (2,400/day) easily supports polling every 15–30 minutes | Designed for this if you pay — purpose-built odds history endpoints | Free tier volume is plenty, but only 2 books = thin market view |
| **Ease of Integration** | Very easy — simple REST/JSON, huge community, countless tutorials | Easy — REST + WebSocket, plain JSON | We already have `fetchers/sportsdataio.py` written and matching our standard shape — lowest marginal effort *if* we pay | Excellent — official Python/TypeScript SDKs, "5 minutes to start" |
| **API Documentation Quality** | Excellent — most mature, most widely used for hobby projects | Good, but smaller community/fewer tutorials | Good, professional-grade | Excellent, modern |
| **Long-Term Suitability for MLB Betting Edge** | Strong — cheap scaling path, $99/mo unlocks player props + full historical archive (useful for Phase 4: parlays, value alerts) | Strong — sharp-book access (Pinnacle) is valuable for "is this a sharp move?" analysis as we grow | Best data depth overall, but cost is likely the blocker until this stops being a "personal project" | Promising but newer/less proven; thin free-tier bookmaker coverage limits usefulness now |

---

## Provider Notes

### 1. The Odds API (the-odds-api.com)
The most widely used hobbyist odds API — if you search for "odds API Python
tutorial," most results use this one. The catch: the free tier is measured
in **credits, not requests**, and each odds request costs around 6 credits.
500 free credits/month works out to roughly 80 calls *total* — about 2-3 per
day. That's too sparse to capture meaningful line movement on its own.

The $30/month tier (20,000 credits ≈ 3,300 calls/month, ~110/day) is
inexpensive and would comfortably support checking odds every hour for all
of today's games.

### 2. OddsAPI.io (odds-api.io)
A newer competitor with a genuinely generous permanent free tier: 100
requests/hour, no credit card, no trial expiration. One request typically
returns odds for *all* of today's MLB games, so 100/hour is far more than
we need — we could poll every 10 minutes and use a fraction of the limit.

It also includes **Pinnacle**, a sportsbook widely considered "sharp" (used
by professional bettors). Comparing a softer book's line against Pinnacle's
is a common technique for spotting value — directly useful for this
project's goals.

### 3. SportsDataIO Odds
We already evaluated SportsDataIO for stats data (see `SETUP_GUIDE.md` and
`backend/fetchers/sportsdataio.py`, currently paused). Their odds product is
the most comprehensive — pre-match, in-play, historical, closing lines,
props, and futures, all in one place.

The problem is cost. Pricing isn't published; based on third-party
comparisons, production odds access likely starts somewhere in the
**$99–$149/month** range. That's a lot for a personal project, especially
before Version 1 has proven useful day-to-day.

**Advantage if we ever do pay for this:** the fetcher already exists and
already returns data in our standard shape. Re-activating it would be a
small code change, not a rebuild.

### 4. SharpAPI (sharpapi.io)
A newer, developer-friendly option with a strong free tier (about 17,280
requests/day) and excellent documentation/SDKs. The catch for us: the free
tier only includes odds from **2 sportsbooks**, and data is delayed by 60
seconds. For line movement tracking, a 60-second delay doesn't matter (we're
not betting in real time), but only seeing 2 books gives a much thinner
picture of "the market" than OddsAPI.io's free tier.

---

## Recommendations

### 1. Best Option for Version 1
**OddsAPI.io (odds-api.io)** — free tier.

- $0/month, no credit card, no expiration
- Request limit (2,400/day) is more than enough to build real line movement
  data by polling every 15-30 minutes
- Includes MLB moneylines and a sharp sportsbook (Pinnacle) from day one
- Simple REST/JSON — fits our existing fetcher pattern with no surprises

### 2. Best Option for Long-Term Growth
**The Odds API (the-odds-api.com)** — paid tiers.

- Cheapest, most well-documented scaling path ($30 → $59 → $119 → $249/mo)
- The $99/mo "Business" tier adds player props (needed for our Phase 2/4
  roadmap: player props, parlay builder) and a full historical odds archive
  at no extra cost — useful for backtesting and "value bet" features later
- Massive community and documentation means fewer dead ends as we grow

### 3. Final Recommendation

**Start with OddsAPI.io's free tier for Version 1.** It costs nothing, the
request limits comfortably support real line-movement tracking, and it
already includes a sharp sportsbook — which fits this project's actual goal
(spotting valuable lines) better than most "free" alternatives.

**Revisit The Odds API's paid tiers later** — specifically when we get to
player props or want a guaranteed historical archive (Phase 2/4 in
`PROJECT_PLAN.md`). At that point, $30/mo is a small, well-justified cost
increase, not a leap of faith.

**Skip SportsDataIO odds and SharpAPI for now.** SportsDataIO's odds pricing
is too high to justify before Version 1 proves its value. SharpAPI's free
tier (2 sportsbooks) gives a thinner view of the market than OddsAPI.io's
free tier, for no real cost advantage.

---

## Outcome (2026-06-16)

OddsAPI.io was selected and is now active.

- [x] Confirmed OddsAPI.io's MLB endpoint shape and signup process
- [x] Confirmed free tier includes MLB moneyline data — live test call
      returned Bet365 and DraftKings odds with no hidden restrictions
- [x] Built `fetchers/odds_api_io.py` using the standard shape; integrated
      into `backend/scripts/save_live_data.py`

The free tier locks the account to two sportsbooks on first use. This
project is locked to **Bet365** and **DraftKings**.

---

## Sources

- [Odds API Pricing in 2026: 4 Providers Compared](https://oddspapi.io/blog/odds-api-pricing-2026-comparison/)
- [Best Odds APIs in 2026: 6 Providers Compared](https://oddspapi.io/blog/best-odds-apis-2026-comparison/)
- [The Odds API — official site](https://the-odds-api.com/)
- [The Odds API — MLB Odds](https://the-odds-api.com/sports-odds-data/mlb-odds.html)
- [The Odds API — FAQs](https://the-odds-api.com/manage/faqs.html)
- [The Odds API Review 2026](https://www.sportbotai.com/blog/tools/the-odds-api-review)
- [Odds-API.io — Free Tier Pricing](https://odds-api.io/pricing/free)
- [Odds-API.io — MLB Odds](https://odds-api.io/sports/mlb)
- [SportsDataIO — Live Odds API](https://sportsdata.io/live-odds-api)
- [SportsDataIO — MLB API Coverage](https://sportsdata.io/developers/coverages/mlb)
- [SharpAPI — MLB Odds API](https://sharpapi.io/odds/mlb)
- [SharpAPI — Pricing](https://sharpapi.io/pricing)
- [SharpAPI — Free Sports Odds API](https://sharpapi.io/compare/free-sports-odds-api)
- [OddsJam — Sports Betting Odds API](https://oddsjam.com/odds-api)
- [8 Free Sportsbook Odds APIs to Consider](https://www.wagerlab.app/7-free-sportsbook-apis-to-consider-this-year/)
