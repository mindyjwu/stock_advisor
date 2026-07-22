# Cleanup notes — automated pass (2026-07-22)

This repo was already in solid shape from prior work (multi-user auth, per-user
data isolation, a Phase-4 FastAPI + Next.js community layer, a clean
`.gitignore`, a genuinely comprehensive README). This pass verified everything
still runs and tightened a few loose ends. Documenting every judgment call
since this ran unattended.

## Verified working (not just "looks fine")

- All `.py` files compile (`py_compile`) — no syntax errors.
- Core modules import cleanly: `agents/*`, `data/*`, `db/*`, `app/auth.py`,
  `app/config.py`, `api/main.py`.
- **Streamlit dashboard actually boots**: `streamlit run app/dashboard.py`
  starts and serves `200` on `localhost:8501`.
- **FastAPI backend actually boots**: `uvicorn api.main:app` starts and
  `/api/health` returns `200`.
- **Next.js web app**: `npm install`, `tsc --noEmit`, and `next build` all
  pass with zero errors across all 6 pages.

## Fixed

- Removed 4 genuinely dead imports/variables found via `pyflakes` (not
  guessed — verified unused via grep across the whole repo first):
  `INTEGRITY_ERRORS` in `db/community.py`, `as_completed` in
  `agents/sentiment.py` and twice in `app/dashboard.py`, and an unused
  `_eq_col` variable in the performance-page equity chart (looks like a
  leftover from when the line color was going to be conditional on
  gain/loss; it's hardcoded indigo now, so the variable was orphaned).
- Fixed a stray f-string with no placeholder in `app/dashboard.py`
  (`f"the rest fine to hold"` → `"the rest fine to hold"`) — cosmetic, not a
  bug, but it's what `pyflakes` flags as dead-giveaway sloppy code.
- Bumped `web/package.json` Next.js `14.2.5` → `14.2.35` — `npm install`
  flagged 14.2.5 with a known security advisory. Stayed on the 14.x line
  (rather than jumping to 15/16) to avoid an unreviewed major-version
  breaking change; rebuilt and reinstalled `package-lock.json` to match.
- Deleted the `invest-cash-and-fixes` branch on GitHub — confirmed via
  `git branch --merged` that it's fully merged into `main`, so it was just
  clutter in the branch list.

## Judgment calls — left alone, flagged for you

- **`ENHANCEMENTS.md`** (244-line roadmap doc) — kept at the repo root rather
  than deleting or moving it. It's not dead code, it's planning notes, and it
  actually reads well as evidence of structured thinking if anyone
  (recruiter, collaborator) browses the repo. Delete it if you'd rather keep
  the root cleaner.
- **`web/` and `api/` were completely undocumented in the top-level README**
  even though they're real, working, tested code (not stubs) — the README's
  "Quick start" and "Project layout" sections only covered the Streamlit
  app. I added a "Community web app (Phase 4)" section linking out to their
  own READMEs rather than deleting the code, since it clearly represents
  deliberate multi-session work (see the `Phase 3` / `Phase 4` commits in
  history), not abandoned scaffolding.
- **Two branches left un-deleted**: `claude/website-enhancements-review-3yj7or`
  and `enhancements`. `git branch --no-merged` shows these as NOT fully
  merged into `main`, even though earlier commits from them were merged via
  PRs #2/#3/#5 — meaning something was pushed to them *after* their last
  merge that never made it to `main`. I didn't dig into what, since deleting
  a branch with unmerged unique commits is destructive and this needs your
  eyes: `git log main..origin/claude/website-enhancements-review-3yj7or` and
  same for `enhancements` will show you exactly what's stranded there.
- **One remaining `npm audit` finding**: a moderate PostCSS XSS advisory,
  transitive via Next.js 14.2.35 itself (not a direct dependency you
  control). The only fix is a Next 15/16 major upgrade, which `npm audit fix
  --force` offered but I didn't take — that's a real breaking-change
  decision for a working app, not a judgment call I should make unattended.

## Not touched

- No dependencies were removed — every package in `requirements.txt`,
  `api/requirements.txt`, and `web/package.json` traced to a real import in
  the codebase.
- No file/folder restructuring — the existing `agents/ data/ db/ app/
  scripts/ api/ web/` layout is already sensible and was left as-is.
