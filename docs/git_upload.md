# Git / GitHub Upload

## Business objective

Publish the final assessment repository cleanly without committing local environments, runtime data, credentials, caches, or generated build noise.

## Technical description

The repository includes a `.gitignore` for local/runtime artifacts and GitHub Actions under `.github/workflows/`. Start with a private repository unless you have confirmed that the original assessment PDF may be shared publicly.

## First local commit

From the project root:

```bash
git init
git branch -M main
git status --short
git add .
git diff --cached --stat
git commit -m "Initial release: invoice canonicalization agent v1.0.0"
```

Before committing, verify that files such as `.env`, `.venv/`, `.runtime/`, `.pytest_cache/`, build directories, and local databases are not staged.

## Create a private GitHub repository with the GitHub CLI

```bash
gh auth login

gh repo create invoice-canonicalization-agent \
  --private \
  --source=. \
  --remote=origin \
  --push
```

Open it in the browser:

```bash
gh repo view --web
```

## Run the strict gate before tagging

```bash
source .venv/bin/activate
make assess-full
```

`make assess-full` requires Ruff, mypy, and Docker. The normal offline gate is:

```bash
./run_assessment.sh
```

## Tag the final assessment delivery

```bash
git tag -a v1.0.0 -m "Assessment delivery v1.0.0"
git push origin v1.0.0
```

The included release workflow reruns the production gate and builds package/container artifacts for tags matching `v*`.
