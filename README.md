# ContinuAI

Project knowledge handover from a Git repository. Connect, reconstruct, verify, review, hand over.

## Run (VS Code terminal)

    python -m venv .venv
    .venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
    pip install -r requirements.txt
    python app.py

Open http://localhost:5000 and click "Try the sample project". Git must be installed to analyze real repositories.

Optional: set `ANTHROPIC_API_KEY` to use Claude for decision extraction. Without it, a rule-based extractor runs. Both tag each claim as confirmed or inferred. Deploy with `gunicorn app:app`.

## Workflow
1. Connect: GitHub URL, `owner/repo`, or local path (read via `git log`).
2. Reconstruct: contribution map, module co-change graph, single-owner risks.
3. Verify: decisions, reasons and rejected alternatives linked to commits; unsupported claims marked inferred; reverts surfaced as conflicts.
4. Review: approve, reject or edit each item. Every change is versioned.
5. Handover: publish approved items only, view by role, confirm receipt. All actions appear in Activity.

## Round 2 notes
- Changes from the plan: dependency graph uses module co-change (static import analysis moves to Round 3); ingestion uses git clone instead of the GitHub API, so PRs and issues are not yet read.
- Suggested Round 3 improvements: GitHub PR and issue ingestion, import/AST dependency analysis, GitHub-team-based access control.

Layout: `app.py` (API, SQLite), `analyzer.py` (analysis), `static/index.html` (UI).

## Deploy on Render
1. Push this folder to a GitHub repository (public, so judges can open it).
2. Render dashboard: New > Blueprint, select the repo. `render.yaml` sets everything up.
3. Or New > Web Service with build command `pip install -r requirements.txt` and start command `gunicorn app:app --workers 1 --threads 4 --timeout 120`.
4. The free plan sleeps after inactivity (first load takes about 50 seconds) and resets the SQLite file on redeploy. Open the link once before judging.
