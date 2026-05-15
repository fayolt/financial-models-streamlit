# Zenkos Financial Models

Unified Streamlit SaaS hosting the Zenkos financial-models catalogue (biotech,
cassava-ethanol, chicken-farming, goat-farming, microbrewery, pharma,
solar-farm) behind email + password auth and Paystack subscriptions, with
tier-gated XLSX/PDF reports and optional LLM commentary on selected models.

Each model lives in its own git repo and is vendored here as a submodule.

## Quick start

```bash
# Clone the parent and pull every model submodule in one go:
git clone --recurse-submodules git@github.com:fayolt/financial-models-streamlit.git
cd financial-models-streamlit

# Python deps:
python3 -m venv .venv
.venv/bin/pip install -e .

# Local services (Docker required):
make db-up          # Postgres on :5433
make migrate        # apply alembic migrations
make seed           # populate the plans table

# Configure secrets:
cp .env.example .env
# Then edit .env — at minimum JWT_SECRET; add Paystack / Mailgun /
# OpenAI / Anthropic keys for the corresponding features.

# Run (two terminals):
make app            # Streamlit on :8501
make api            # FastAPI (webhooks) on :8000
```

If you already cloned without `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

## Architecture

- `app/` — Streamlit frontend, auth, db models, admin, reports service.
- `api/` — FastAPI service for Paystack webhooks (separate process).
- `models/<slug>/plugin.py` — adapter per model implementing `ModelPlugin`.
- `<slug>/` (the 7 top-level dirs) — **submodules** with the legacy model code,
  pinned to specific SHAs.
- `tests/` — pytest suite, 156 tests against the live local Postgres.
- `migrations/` — alembic.
- `Makefile` — common dev commands (`make help`).

## Working with model submodules

### Bumping a model to a newer commit

When you change code inside a model — e.g. fix a bug in `microbrewery/`:

```bash
# 1. Edit + commit inside the submodule, push to its remote.
cd microbrewery
# … edit files …
git add finmodel/core.py
git commit -m "Fix off-by-one in WACC formula"
git push                       # pushes to github.com/Kossit73/Microbrewery

# 2. Tell the parent to point at the new SHA.
cd ..
git add microbrewery           # records the new pinned SHA
git commit -m "Bump microbrewery to <short SHA>"
git push                       # pushes to github.com/fayolt/financial-models-streamlit
```

The parent's commit captures **which version of each model is currently in
production**. Bumping = "the parent now points at a different commit".

### Pulling someone else's model bump

If a teammate bumped a submodule and pushed, your working copy will lag until
you tell git to fetch + checkout the new SHA:

```bash
git pull                                  # updates the parent + .gitmodules
git submodule update --init --recursive   # checks out the SHAs the parent now pins
```

Add `--recursive` even when no submodule has its own submodules — it's a no-op
in that case but a habit worth keeping.

### Detecting drift

Three commands diagnose submodule state:

| Command | What it tells you |
|---|---|
| `git submodule status` | Each submodule's pinned SHA. `+SHA` = working tree is ahead of the pin (you have local commits the parent doesn't know about). `-SHA` = not initialized (run `git submodule update --init`). |
| `git submodule summary` | Per-submodule list of commits between the parent's pinned SHA and the submodule's current `HEAD`. |
| `git submodule foreach 'git status'` | Run any command inside every submodule — useful for spotting dirty trees in bulk. |

If you see a `+` prefix in `git submodule status` and you didn't intend to bump
that model, you probably want `git submodule update <path>` to reset to the
pinned SHA.

### Adding a new model

To onboard model #8:

```bash
git submodule add git@github.com:Kossit73/NewModel.git new-model
git submodule update --init new-model

# Create the plugin adapter at models/new-model/plugin.py
# (use models/microbrewery/plugin.py as a template).

.venv/bin/pytest tests/test_plugin_contract.py -k new-model
git add .gitmodules new-model models/new-model
git commit -m "Add new-model financial model"
```

The plugin contract (`app/plugin/contract.py`) is the single point of
integration — once the contract test passes, the model appears in the
unified Streamlit nav automatically.

### Common pitfalls

- **Editing a submodule and forgetting to commit there**: the parent records
  no change, your edits stay in the submodule's working tree only and vanish
  on the next `git submodule update`. Always commit *inside* the submodule
  first, then bump in the parent.
- **Pushing the parent SHA bump but not the submodule commit**: the new SHA
  exists locally but not on the submodule's remote. CI / fresh clones can't
  fetch it. The parent's submodule reference becomes a dangling pointer.
- **Cloning without `--recurse-submodules`**: model directories will be empty
  and `make app` will `ImportError` immediately. Run
  `git submodule update --init` to recover.

## Dev commands

`make help` lists everything. The day-to-day set:

```
make db-up           # start Postgres
make db-down         # stop Postgres
make migrate         # apply alembic migrations
make seed            # seed Free / Pro / Enterprise plans
make app             # run Streamlit on :8501
make api             # run FastAPI on :8000
make test            # run the full pytest suite
make paystack-check  # diagnose Paystack config + DB plans
make paystack-sync   # pull plan_codes from Paystack into the DB
```

## Admin bootstrap

The first admin has to be promoted from the shell:

```bash
.venv/bin/python -m app.admin promote you@example.com
.venv/bin/python -m app.admin list
```

After re-logging in, an **Admin** section appears in the sidebar with user
management and analytics.
