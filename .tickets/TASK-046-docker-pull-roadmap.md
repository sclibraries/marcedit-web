# TASK-046 — Docker pull deployment and improvement roadmap

## Title

Docker pull deployment path and current application improvement view

## Scope

- Add a pull-only Docker Compose file so deployment hosts can run a published image without checking out source code or rebuilding locally.
- Add a GitHub Actions workflow that builds and publishes the container image to GHCR.
- Update deployment and README documentation with build, pull, and production run paths.
- Capture the current application architecture and prioritized speed, consistency, and hardening improvements.

## Success Criteria

- Operators can run the app from a pulled image by setting `MARCEDIT_WEB_IMAGE` and using a pull-only compose file.
- The repository includes a CI workflow capable of publishing `ghcr.io/<owner>/<repo>` images on main and tags.
- Documentation clearly distinguishes local development builds from pulled-image deployment.
- The application overview names the major workflows, current strengths, and next improvement areas.
- `docker compose -f docker-compose.pull.yml config` succeeds.
- `git diff --check` succeeds.

## Validation

- `MARCEDIT_WEB_IMAGE=ghcr.io/example/marcedit-web:latest docker compose -f docker-compose.pull.yml config`
- `docker compose config`
- `ruby -e "require 'yaml'; YAML.load_file('.github/workflows/docker-publish.yml'); puts 'workflow yaml ok'"`
- `docker compose build`
- `docker compose run --rm marcedit-web pytest -q` — 499 passed
- `git --no-pager diff --check`
- VS Code diagnostics — no errors

## Status

Completed