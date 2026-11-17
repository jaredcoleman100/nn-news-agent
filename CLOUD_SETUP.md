# Moving the morning publish to GitHub Actions

Step by step. Run every command from the repo:

```
cd "H:\Shared drives\Coleman & Associates\Norway\nn-news-agent"
```

The repo is already a git repo with two commits on `main`, 177 files, 547 KB. The 162 MB item
archive is excluded — it is derived and it is not ours to publish.

---

## 1. Install the GitHub CLI

```
winget install --id GitHub.cli -e
```

Then **close this terminal and open a new one** — `gh` will not be on your PATH until you do.
Check it worked:

```
gh --version
```

---

## 2. Sign in to GitHub

```
gh auth login
```

Answer: **GitHub.com** → **HTTPS** → **Yes** (authenticate Git with your GitHub credentials) →
**Login with a web browser**. It shows an eight-character code, you press Enter, a browser opens,
you paste the code and approve.

I cannot do this step for you — it is your account, and the credential never passes through here.

Check:

```
gh auth status
```

---

## 3. Create the repository and push

```
gh repo create nn-news-agent --private --source=. --remote=origin --push
```

**`--private` matters.** The code is fine to show, but `config/` holds your source list and beat
definitions, and `vendor/norlit-outbox` holds Norlit's unpublished writing.

Check:

```
gh repo view --web
```

---

## 4. Set the five secrets

Four come from your `.env`. The fifth, `OPENAI_API_KEY`, is **not in any `.env` file** — it is a
Windows environment variable on this machine. (`ANTHROPIC_API_KEY` is in `.env` but empty; nothing
uses it.) This loop reads both sources and uploads each value straight to GitHub. **Nothing is
printed** — not to the screen, not to your shell history.

Git Bash:

```bash
for k in SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY GEMINI_API_KEY CLOUDFLARE_API_TOKEN; do
  v=$(grep -m1 "^$k=" "$HOME/.config/nn-news-agent/.env" | cut -d= -f2-)
  if [ -n "$v" ]; then printf '%s' "$v" | gh secret set "$k" && echo "set $k"; else echo "MISSING $k"; fi
done
printf '%s' "$OPENAI_API_KEY" | gh secret set OPENAI_API_KEY && echo "set OPENAI_API_KEY"
```

Check all five are there (names and dates only — GitHub cannot show you a secret again):

```
gh secret list
```

You should see exactly: `CLOUDFLARE_API_TOKEN`, `GEMINI_API_KEY`, `OPENAI_API_KEY`,
`SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_URL`.

---

## 5. Run it once by hand, before trusting the schedule

```
gh workflow run morning.yml
gh run watch
```

The run takes roughly 3–5 minutes. What should happen:

| Step | Expected |
| --- | --- |
| Install toolchain | pip + npm install, ~1 min |
| Draft today's brief | drafts, **or** `skip: daily-digest already has a report for today (Oslo)` |
| Build and deploy | `deployed NN pages to Cloudflare Pages` |
| Verify the live site | front page 200, Norlit links ≥ 1, five archive paths all 404 |

If the draft step fails, that is **not** a failed run. It is wired to continue, because drafting
dies whenever the Gemini credits run dry, and a page frozen at yesterday with nothing saying so is
worse than a page that refreshes and shows its own build stamp. The deploy runs regardless.

If a step does fail:

```
gh run view --log-failed
```

---

## 6. Retire the laptop (updated 2026-11-17)

Both halves of the pipeline now run in the cloud:

| Job | Cloud | Since |
| --- | --- | --- |
| Read the feeds, embed, score | `ingest.yml`, hourly at :40, bge-m3 in a container on the runner | 2026-11-02 |
| Draft every scheduled `nord-norge` desk, build, deploy | `morning.yml`, morning slots plus three weekday afternoon slots for the 14:00 desk | 2026-10-04, afternoon slots 2026-11-17 |
| Email delivery | Supabase pg_cron `drain-outbox` -> `send-outbox` Edge Function | 2026-09-14 |

The ingest backlog that used to pin `NNNewsAgentIngest` to this machine is gone: the cloud uses
the same bge-m3 build, asserted by digest, so no re-embedding was needed.

### Before switching the laptop off, three things

1. **Fix the OpenAI secret.** On 2026-11-17 `OPENAI_API_KEY` in GitHub held an Anthropic key
   (`sk-ant-...`), so `editor-letter` fails every cloud run with a 401 and only the laptop writes
   it. Re-set it from the machine that has the right key:

   ```bash
   printf '%s' "$OPENAI_API_KEY" | gh secret set OPENAI_API_KEY
   ```

   The secrets step now warns when a key starts with another vendor's prefix.

2. **Decide where norlit's pieces come from.** The cloud build reads `vendor/norlit-outbox`,
   which only moves when the laptop copies norlit's live outbox into it and someone commits and
   pushes. With the laptop off, the magazine freezes at the last pushed snapshot (it does not
   vanish). norlit has to deliver its outbox somewhere the cloud can read before this stops
   depending on the laptop.

3. **Decide on the satire desk.** `rikspolitikk/satire-desk` has a different owner and is not
   drafted in the cloud (`morning.yml` runs `--newsroom nord-norge` only). If the laptop drafts
   it today, switching the laptop off stops it.

### Then

```powershell
Disable-ScheduledTask -TaskName NNNewsAgentIngest
Disable-ScheduledTask -TaskName NNNewsAgentDigest
Disable-ScheduledTask -TaskName NNNewsAgentPublish
```

Disable, not unregister, so any of them can come back with `Enable-ScheduledTask` if a cloud run
misbehaves. After a week of green `ingest` and `morning` runs with the laptop off, delete them.

---

## When it runs

Three attempts daily, at 03:00, 04:00 and 05:00 UTC:

| UTC | Oslo (CEST, to 25 Oct) | Oslo (CET, from 26 Oct) |
| --- | --- | --- |
| 03:00 | 05:00 | 04:00 |
| 04:00 | 06:00 | 05:00 |
| 05:00 | 07:00 | 06:00 |

All comfortably inside the 08:00 Oslo deadline. Three attempts rather than one because GitHub's
cron runs ten to thirty minutes late under load and occasionally skips a slot outright. Repeating
is safe: the first attempt drafts and deploys, the other two find today's brief already written,
skip the draft, and redeploy.

---

## Afterwards

Your editing workflow does not change. The repo stays on the shared drive, Claude Code still edits
it in place. The one new habit is that changes only reach the cloud when committed and pushed:

```
git add -A && git commit -m "..." && git push
```

One caveat about this repo living on Google Drive: Drive syncs `.git` too. With one machine that is
normally fine, but do not run git operations from two machines at once, and if Drive ever reports a
conflict inside `.git`, re-clone from GitHub rather than trying to repair it.
