# Backend work

- Preserve deployed API paths, response envelopes and legacy environment aliases. Coordinate any client contract changes explicitly.
- Never print `.env`, signing keys, token payloads or raw historical `config/settings.py`; Git history contains a legacy SMTP credential. Keep private keys and credentials outside Git. Deployment requires EMAIL_HOST_PASSWORD in the server environment and correct API_DOMAIN/BASE_DOMAIN mail destinations.
- Do not modify production databases, services or provider consoles during local development. Keep historical migrations and backups.
- Use isolated local tests from `rollpe/`: `python manage.py test --settings=config.test_settings`. This uses SQLite and local email rather than the production environment.
- Run `python manage.py makemigrations --check --dry-run --settings=config.test_settings` after model-related changes. A local test pass does not verify real provider login or mobile behavior.
- Configuration diagnostics: `python manage.py check_social_auth`. Expired flow cleanup is a preview unless `--apply` is supplied; review the bounded preview before scheduling it.
- Keep changes focused; do not upgrade dependencies or reformat unrelated files. Do not stage, commit or push unless requested.
