# TASK-065 — Mount Compose config for Docker tests

**Status:** Completed

## Title

Mount `docker-compose.yml` in the local Docker test container.

## Scope

- Update local `docker-compose.yml` so tests running inside the container can
  read `docker-compose.yml`.
- Keep the file read-only inside the container.
- Do not change production deployment behavior.

## Success Criteria

1. `tests/test_docker_compose_config.py` passes inside `docker compose run`.
2. The full Docker test suite can read the Compose config file.
