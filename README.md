# GitOps for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/jxnix-lab/homeassistant-gitops.svg)](https://github.com/jxnix-lab/homeassistant-gitops/releases)
[![License](https://img.shields.io/github/license/jxnix-lab/homeassistant-gitops.svg)](LICENSE)

GitOps-style configuration management for Home Assistant. Polls your Git repository for new commits, shows them as available updates (like HACS), and deploys with smart component reloading when you're ready.

## How It Works

1. **You push** configuration changes to your Git repo
2. **GitOps polls** (or receives a webhook) and detects new commits
3. **Update appears** in the HA UI — just like HACS shows pending updates
4. **You deploy** by clicking "Install" in the UI, or via the `gitops.deploy` service call
5. **Smart reload** — only changed components are reloaded, no unnecessary restarts

No GitHub Actions runner required. No CI/CD pipeline. Just Git and Home Assistant.

## Features

- **HACS-style updates** — New commits show as available updates with commit log
- **Smart reloading** — Only reloads automations, scripts, groups, etc. that actually changed
- **Config validation** — Runs `ha core check` before applying changes
- **Doppler secrets sync** — Automatically syncs secrets on startup and each deploy
- **Service calls** — `gitops.deploy` and `gitops.check_updates` for automation and agents
- **Webhooks** — Optional push notifications from GitHub for instant detection
- **Drift detection** — Detects uncommitted local changes (UI edits, manual tweaks)
- **Crash recovery** — Detects interrupted deployments on restart

## Installation

### HACS (Recommended)

1. HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/jxnix-lab/homeassistant-gitops` as integration
3. Install → Restart HA

### Manual

Copy `custom_components/gitops/` to `config/custom_components/` and restart.

## Prerequisites

### Git Repository

Your HA config directory must be a Git repo with an SSH remote:

```bash
cd /config
git init
git remote add origin git@github.com:you/your-ha-config.git
ssh-keygen -t ed25519 -f /config/.ssh/id_ed25519 -N ""
# Add public key as deploy key in GitHub repo settings
git add . && git commit -m "Initial" && git push -u origin main
```

### Doppler Service Token

[Create a service token](https://docs.doppler.com/docs/service-tokens) scoped to your project and config. This gives the integration read-only access to sync secrets into `secrets_doppler.yaml`.

## Setup

Settings → Devices & Services → Add Integration → **GitOps**

| Field | Description | Default |
|-------|-------------|---------|
| Doppler Service Token | `dp.st.xxx` scoped to your project/config | — |
| Doppler API URL | Override for self-hosted Doppler | `https://api.doppler.com` |
| Update Check Interval | Seconds between git fetch polls | `300` (5 min) |
| Enable Drift Detection | Check for uncommitted local changes | `false` |
| Drift Check Interval | Seconds between drift checks | `300` |

## Usage

### Update Entity

When new commits are detected, the update entity shows:

- Current version (local commit SHA)
- Available version (remote commit SHA)
- Release notes (commit log with messages)
- "Install" button to deploy

Works exactly like HACS updates in the HA dashboard.

### Service Calls

```yaml
# Deploy latest (pull → secrets sync → validate → reload)
service: gitops.deploy

# Check for new commits now (don't wait for next poll)
service: gitops.check_updates
```

Use `gitops.deploy` in automations, scripts, or have your AI assistant call it.

### Webhooks

Two lightweight webhooks are registered automatically:

| Webhook | Purpose |
|---------|---------|
| `gitops-notify` | Triggers immediate update check (set this as a GitHub repo webhook) |
| `gitops-secrets-refresh` | Triggers Doppler secrets re-sync |

To get instant push detection, add a GitHub webhook (repo settings → Webhooks) pointing to:
```
https://your-ha-instance/api/webhook/gitops-notify
```
No secret needed — worst case someone triggers an extra `git fetch`.

### Sensors

- **`sensor.gitops_deployment_status`** — Last deploy result (idle/deploying/success/failed)
- **`sensor.gitops_current_commit`** — Current commit SHA, commits behind, update available

### Secrets Sync

On startup and each deploy, secrets from Doppler are written to `/config/secrets_doppler.yaml` and automatically included in `secrets.yaml`. Reference them as `!secret SECRET_NAME`.

### Deployment Flow

1. Git pull (fetch new config files)
2. Doppler sync (refresh secrets — new config may reference new secrets)
3. Validate (`ha core check`)
4. Smart reload (only changed components)
5. If core config changed → repair issue prompting restart

### Smart Reloading

| Changed Files | Reloaded |
|---------------|----------|
| `automations.yaml` | Automations |
| `scripts.yaml` | Scripts |
| `groups.yaml` | Groups |
| `scenes.yaml` | Scenes |
| `configuration.yaml` | Groups, templates, inputs (+ restart prompt) |

## Migrating from v1

v2 replaces Infisical with Doppler and removes the GitHub Actions dependency.

1. Update the integration files
2. Remove the existing GitOps config entry
3. Re-add with your Doppler service token
4. `secrets.yaml` will automatically update its include from `secrets_infisical.yaml` to `secrets_doppler.yaml`
5. Delete `/config/secrets_infisical.yaml` after verifying
6. The GitHub Actions deploy workflow is no longer needed — you can remove it

## Troubleshooting

**Git lock file** — `rm /config/.git/index.lock`

**Doppler connection** — Check token validity, network access to `api.doppler.com`

**SSH issues** — Verify key exists at `/config/.ssh/id_ed25519`, test with `ssh -T git@github.com`

**Debug logging:**
```yaml
logger:
  logs:
    custom_components.gitops: debug
```

## License

MIT — see [LICENSE](LICENSE).
