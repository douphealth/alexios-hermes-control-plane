# Security policy

## Secrets

Never commit API keys, Telegram bot tokens, WordPress credentials, Cloudflare tokens, OAuth refresh tokens, SSH material, production database passwords, or private certificates.

## Production-write boundary

Production writes are disabled by default. Future write-capable activities must require all of the following:

- scoped capability credentials;
- explicit Temporal approval signal;
- exact object/site write lock;
- pre-change backup;
- reversible canary;
- deterministic stored-state and public-state verification;
- rollback path;
- independent verifier pass.

## Telegram

Production deployments must configure a Telegram webhook secret and explicit allowed user IDs. The webhook handler is idempotent to Telegram retries.

## Model providers

No provider may silently substitute another model. Provider/model identity is recorded by the orchestrator. OpenAI responses are configured with `store=false` by default.

## Incident handling

Treat leaked credentials, unauthorized mutation capability, cross-site write-lock violations, or false verification claims as critical incidents. Disable write capability first, preserve evidence, rotate affected credentials, and reconcile the execution ledger before resuming automation.
