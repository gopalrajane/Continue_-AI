# ContinuAI

A repository knowledge handover tool that analyzes Git history to help teams understand project contributions, technical decisions, and ongoing work.

## Features

- Analyze a public Git repository or local repository
- Build a contribution summary from commit history
- Explore module relationships using file co-change data
- Extract decisions and distinguish confirmed information from inferred information
- Review, edit, and track handover notes
- Store handover data and activity in SQLite
- Optional Claude-based decision extraction

## Tech Stack

Python, Flask, SQLite, NetworkX, Git, and optional Anthropic API integration.

## Project Structure

```text
Continue_-AI/
├── app.py
├── analyzer.py
├── requirements.txt
├── render.yaml
└── static/
    └── index.html
```

## Run Locally

```bash
git clone https://github.com/gopalrajane/Continue_-AI.git
cd Continue_-AI
python -m venv .venv
```

Activate the environment and install dependencies:

```bash
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000 in your browser. Git must be installed to analyze repositories. Set `ANTHROPIC_API_KEY` to enable optional Claude-based extraction.

## Deployment

A Render configuration is included in `render.yaml`.

