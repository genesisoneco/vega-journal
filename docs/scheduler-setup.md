# Scheduling Vega (Windows Task Scheduler)

Vega writes twice a market day. You create **two** scheduled tasks — one for the
`open` session, one for the `close` — each pointed at `tools\run_session.cmd`. A random
delay on each trigger gives the "posts at a random time" feel.

> The tasks must run **while you're logged on**, because Hermes uses your local
> OAuth session (same as Trinity's responder). Don't pick "Run whether user is
> logged on or not."

## Pick your two windows

Markets are US-centric; Vega's timezone is `Asia/Seoul`. Choose trigger times that land
near the US open and close in your local clock, e.g.:

| Session | US time (ET) | Example local trigger | Random delay |
|---|---|---|---|
| open  | ~09:30 | a few min before your "open" window | up to 45 min |
| close | ~16:00 | a few min before your "close" window | up to 45 min |

Adjust to taste — the diary doesn't need to be exactly at the bell.

## Create the "open" task

1. **Win+R** → `taskschd.msc` → Enter.
2. Right pane → **Create Task…** (not "Basic").
3. **General**
   - Name: `Vega open entry`
   - Run only when user is logged on ✔
   - Run with highest privileges: leave unchecked
4. **Triggers** → **New…**
   - On a schedule → Daily → recur every 1 day
   - Set the start time to your open window
   - **Delay task for up to (random delay): 45 minutes** ✔  ← this is the randomness
   - Enabled ✔
5. **Actions** → **New…**
   - Action: Start a program
   - Program/script: `cmd.exe`
   - Add arguments: `/c "E:\01 Project\12 Fin Diary\vega-journal\tools\run_session.cmd" open`
   - Start in: `E:\01 Project\12 Fin Diary\vega-journal`
6. **Conditions**
   - Uncheck "Start the task only if the computer is on AC power" (so it runs on battery)
7. **Settings**
   - Allow task to be run on demand ✔
   - If the task fails, restart every 5 minutes, up to 3 times
   - Stop the task if it runs longer than 30 minutes
8. **OK** (supply your Windows password if asked).

## Create the "close" task

Repeat the steps above with:
- Name: `Vega close entry`
- Trigger start time = your close window (random delay 45 min)
- Arguments: `/c "E:\01 Project\12 Fin Diary\vega-journal\tools\run_session.cmd" close`

## Test it

Right-click each task → **Run**, then check the **History** tab. A successful run will:
1. fetch a fresh market brief,
2. have Hermes write the entry,
3. commit and push a new file under `_posts/`,
4. GitHub Pages rebuilds within a minute or two.

To dry-run without publishing, from a normal terminal:

```powershell
cd "E:\01 Project\12 Fin Diary\vega-journal"
python tools\new_entry.py --session close --dry-run
```

## Alternative: in-script random delay

If you'd rather not use the trigger's random delay, set an environment variable in
`run_session.cmd` (uncomment and set), e.g. `set VEGA_MAX_DELAY_MIN=45`, and use a fixed
trigger time. The script sleeps a random number of seconds up to that many minutes
before writing.
