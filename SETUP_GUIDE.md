# Setup Guide — MLB Betting Edge

This guide explains everything you need before writing a single line of code.
No technical experience required.

---

## 1. What Is SportsDataIO?

SportsDataIO is a company that collects sports data and sells access to it.

Think of it like a newspaper stand. The newspaper (data) gets updated constantly —
game schedules, scores, player stats, betting odds. You pay a subscription fee and
they give you a private door to walk in and read whatever you need.

In our case, we will use SportsDataIO to get:
- Today's MLB game schedule
- Starting pitcher announcements
- Moneyline odds (and updates throughout the day)
- Team win/loss records

Without a data provider like this, you would have to manually collect all of this
information yourself. That would take hours every day.

---

## 2. What Is an API Key?

**API** stands for "Application Programming Interface." That is a fancy term for
a door that lets two programs talk to each other. Our Python code will knock on
SportsDataIO's door and ask for data.

An **API key** is your personal password for that door.

Real-world analogy:

> Imagine a gym. Anyone can try to walk in, but you need a membership card to
> get through the turnstile. Your API key is your membership card. It tells
> SportsDataIO "this request is from a paying customer — let them in."

Every request we make to SportsDataIO will include our API key.
Without it, the API will reject us and return an error.

---

## 3. Where Do I Get the API Key?

1. Go to **https://sportsdata.io**
2. Click **"Sign Up"** or **"Free Trial"**
3. Create an account with your email address
4. Once logged in, navigate to **"My Account"** or **"API Keys"**
5. You will see a key that looks something like this:

```
a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4
```

That long string of random letters and numbers is your API key. Copy it somewhere safe.

**Important:** You will need access to the **MLB** endpoints specifically.
When signing up or managing your subscription, confirm you have access to:
- MLB Game Scores & Schedules
- MLB Odds (for moneyline data)

---

## 4. How Much Does It Cost?

SportsDataIO pricing changes over time, so always check the current plans at:
**https://sportsdata.io/mlb-api**

**What to know before you sign up:**

- They offer a **free trial** (typically 14–30 days) — use this to build Version 1
- After the trial, you pay a monthly subscription
- **Stats data** (scores, schedules, standings) is cheaper
- **Odds data** (moneylines, line movement) may require a separate or higher-tier plan
- For a personal project, look for the lowest tier that includes both **MLB stats** and **MLB odds**

**Budget tip:** Build the whole Version 1 dashboard during the free trial.
Only pay once you know the data is flowing correctly and it's worth continuing.

---

## 5. Where the API Key Will Be Stored in This Project

Your API key will live in a file called **`.env`** inside the `backend` folder.

```
mlb-betting-edge/
├── backend/
│   └── .env          ← your secret keys live here (NEVER shared)
├── .env.example      ← a safe template showing what variables are needed
└── ...
```

The `.env` file is **private**. It never gets uploaded to GitHub or shared with
anyone. The `.env.example` file is a blank template that shows what variables
are needed — without the real values. That one is safe to share.

---

## 6. How Environment Variables Work

An environment variable is a named value your program can read at runtime
without it being written directly in the code.

Think of it like this:

> You are writing a letter to a friend. Instead of writing your home address
> directly in the letter (where anyone who reads it would see it), you write
> "see the envelope for my return address." The envelope is your `.env` file.
> The letter is your code.

Here is the difference in Python:

**Bad — key is written directly in the code:**
```python
api_key = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
```

**Good — key is read from an environment variable:**
```python
import os
api_key = os.getenv("SPORTSDATAIO_API_KEY")
```

In the good version, the code just says "go read the variable called
`SPORTSDATAIO_API_KEY` from the environment." The actual value is stored
in the `.env` file separately. The code and the secret never touch.

**How Python loads `.env` files:**
We use a library called `python-dotenv`. When your backend starts, it reads
the `.env` file and loads all the variables into memory automatically.
We will set this up in the next step.

---

## 7. Why We Never Save API Keys Directly in Code

Three reasons:

**Reason 1 — Accidental sharing**
Code gets shared. You might push it to GitHub, send it to a friend, or copy it
into a forum asking for help. If your API key is written in the code, it goes
with it. Someone can steal it and run up charges on your account.

**Reason 2 — You can't easily change it**
If your API key expires or gets compromised, you have to hunt through every
file to find and replace it. With environment variables, you change one line
in one file.

**Reason 3 — Different environments need different values**
On your laptop (development), you use one database.
On the live server (production), you use a different database.
Environment variables let you swap these out without touching the code at all.

**The rule: treat an API key like a password. You would not write your
banking password in a Python file. Do the same for API keys.**

---

## Variables We Will Need

These two variables power everything in Version 1.

---

### `SPORTSDATAIO_API_KEY`

What it is: Your personal key from SportsDataIO.

How it gets used: Every API request we make will include this key in the URL
or request header so SportsDataIO knows it's us.

Example format: `a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4`

---

### `DATABASE_URL`

What it is: The address of your PostgreSQL database, including login credentials.

Think of it as the full address and key to your filing cabinet —
it tells Python where the database lives and how to log into it.

Format breakdown:
```
postgresql://username:password@host:port/database_name
             │         │        │     │   └── name of your database
             │         │        │     └─── port (PostgreSQL default is 5432)
             │         │        └───────── host (localhost = your own machine)
             │         └────────────────── your PostgreSQL password
             └──────────────────────────── your PostgreSQL username
```

Local development example:
```
postgresql://postgres:mypassword@localhost:5432/mlb_betting_edge
```

When we move to Supabase later, this URL will change to point to their servers
instead of your local machine — and we just update this one variable.

---

## Summary Checklist

Before running any code, you need:

- [ ] A SportsDataIO account with MLB access
- [ ] Your API key copied and ready
- [ ] PostgreSQL installed on your machine
- [ ] A database created called `mlb_betting_edge`
- [ ] A `.env` file inside the `backend/` folder with both variables filled in

The next step will walk through creating that `.env` file.
