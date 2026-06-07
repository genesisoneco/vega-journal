# Scheduling Vega on sejcore (Linux cron)

The autonomous agent ("Ares") runs Vega's Bell on the Linux box `sejcore` from
`/home/sejcore/projects/vega-journal`. Four cron jobs keep it live:

| Job | What it does | Suggested cadence |
|---|---|---|
| **open**  | writes the open-session entry  | once near the US market open |
| **close** | writes the close-session entry | once near the US market close |
| **responder** | answers pending "Ask Vega" questions | hourly |
| **grader** | resolves due predictions (HIT/MISS) | once daily |
| **radar** *(new)* | writes a topical "On the Radar" piece on a trending catalyst | a few times a week |
| **reflect** *(new)* | updates calibration + self-rewrites the playbook | weekly |

The **radar** and **reflect** jobs are optional but recommended. Radar pieces are
the subscriber-growth lever (topical takes on IPOs, the Fed, big earnings).
Reflect is the self-improvement pass that keeps Vega learning.

## 1. Optional local env

Cron runs with a bare environment. Put machine-specific config in
`tools/.env` (gitignored) so every job picks it up:

```bash
# tools/.env  (on sejcore only - never commit)
HERMES_BIN=hermes
HERMES_PROVIDER=openai-codex
HERMES_MODEL=gpt-5.5
VEGA_ADMIN_TOKEN=...            # also in tools/.pipeline-token
VEGA_PYTHON=python3
# Email (only once the Brevo domain is authenticated):
# BREVO_API_KEY=xkeysib-...
# VEGA_FROM_EMAIL=Vega's Bell <vega@vegabell.com>
VEGA_NOTIFY=1                   # email subscribers after each new entry
```

## 2. Install the crontab

`crontab -e`, then paste (using `CRON_TZ` so the writer tracks the US market
through DST automatically; adjust to taste):

```cron
CRON_TZ=America/New_York
REPO=/home/sejcore/projects/vega-journal

# open: ~09:25 ET, weekdays. run_session.sh adds an optional random delay.
25 9 * * 1-5  cd $REPO && VEGA_MAX_DELAY_MIN=20 tools/run_session.sh open  >> $REPO/tools/cron.log 2>&1
# close: ~15:55 ET, weekdays
55 15 * * 1-5 cd $REPO && VEGA_MAX_DELAY_MIN=20 tools/run_session.sh close >> $REPO/tools/cron.log 2>&1
# responder: hourly
0 * * * *     cd $REPO && python3 tools/respond_to_prompts.py >> $REPO/tools/cron.log 2>&1
# grader: daily at 06:00 ET
0 6 * * *     cd $REPO && python3 tools/grade_predictions.py  >> $REPO/tools/cron.log 2>&1

# --- optional: topical pieces + self-improvement ---
# radar: Tue/Thu ~12:00 ET. Omit --topic to auto-pick from trending; or set one.
0 12 * * 2,4  cd $REPO && python3 tools/new_entry.py --session radar >> $REPO/tools/cron.log 2>&1
# reflect: weekly, Sunday 07:00 ET (recompute calibration, rewrite the playbook)
0 7 * * 0     cd $REPO && python3 tools/reflect.py >> $REPO/tools/cron.log 2>&1
```

To steer a radar piece at a specific catalyst, run it by hand any time:

```bash
cd $REPO && python3 tools/new_entry.py --session radar --topic "SpaceX IPO"
# preview without publishing:
python3 tools/new_entry.py --session radar --topic "SpaceX IPO" --dry-run
```

Make the runner executable once: `chmod +x tools/run_session.sh`.

Cover thumbnails need Pillow (fonts are bundled in `tools/fonts/`):
`pip install -r tools/requirements.txt`. To turn on AI-generated cover art,
set `VEGA_IMAGE_KEY` (an OpenAI API key) in `tools/.env`; without it, covers use
the bundled designed style.

## 3. Verify

```bash
cd /home/sejcore/projects/vega-journal
python3 tools/verify_cron.py
```

It reports `[OK]` / `[MISSING]` for each of the four jobs and exits non-zero if
any are absent. Then confirm the pipeline end-to-end with a dry run (no commit):

```bash
python3 tools/new_entry.py --session close --dry-run
```

## Notes

- Jobs run under the agent's user, so its Hermes OAuth session must be active.
- `tools/cron.log` is the first place to look if an entry doesn't appear.
- The writer pushes to `main`; GitHub Pages rebuilds and serves at
  https://vegabell.com within a minute or two.
