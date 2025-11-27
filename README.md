# GitOps for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/jxnix-labs/homeassistant-gitops.svg)](https://github.com/jxnix-labs/homeassistant-gitops/releases)
[![License](https://img.shields.io/github/license/jxnix-labs/homeassistant-gitops.svg)](LICENSE)

Bring modern GitOps principles to Home Assistant! This integration enables automated configuration deployments triggered by Git pushes, with intelligent component reloading, comprehensive deployment tracking, and real-time status updates.

## Features

### Core Functionality
- **🚀 Automated Git-based Deployments** - Push to your Git repository and watch configurations deploy automatically
- **🔒 Secure Webhook Integration** - HMAC-SHA256 signature verification for secure deployments
- **🎯 Smart Component Reloading** - Automatically detects which components changed and reloads only those
- **📊 Real-time Deployment Tracking** - SSE streaming of deployment progress back to GitHub Actions
- **⚡ Crash Recovery** - Detects interrupted deployments and creates repair issues
- **🔄 Configuration Drift Detection** - Periodic checks for uncommitted local changes

### Deployment Intelligence
- **Selective Reloading** - Automatically reloads automations, scripts, groups, scenes, and more based on changed files
- **Restart Detection** - Identifies when configuration changes require a full Home Assistant restart
- **Validation** - Runs `ha core check` before reloading to catch configuration errors
- **Rollback Support** - Failed deployments don't apply changes, maintaining system stability

### Optional Features
- **🔐 Infisical Integration** - Sync secrets from Infisical secrets manager (BETA)
- **📈 Deployment Sensors** - Track current commit SHA, deployment status, git status, and drift status
- **🔔 GitHub Actions Integration** - Seamlessly integrates with GitHub Actions for CI/CD workflows

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant instance
2. Click on "Integrations"
3. Click the three dots menu in the top right and select "Custom repositories"
4. Add `https://github.com/jxnix-labs/homeassistant-gitops` as an integration repository
5. Click "Install" on the GitOps integration
6. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/gitops` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant
3. Go to Settings → Devices & Services → Add Integration
4. Search for "GitOps" and follow the configuration flow

## Prerequisites

### 1. Git Repository Setup

Your Home Assistant configuration must be managed in a Git repository:

```bash
cd /config
git init
git remote add origin <your-repo-url>
git add .
git commit -m "Initial commit"
git push -u origin main
```

**SSH Authentication (Recommended):**

For automated deployments, configure SSH key authentication:

```bash
# Generate SSH key on Home Assistant
ssh-keygen -t ed25519 -f /config/.ssh/id_ed25519 -N ""

# Add public key to GitHub
cat /config/.ssh/id_ed25519.pub
# Copy the output and add as a deploy key in GitHub repo settings

# Configure git to use SSH
git remote set-url origin git@github.com:your-username/your-repo.git
```

### 2. GitHub Actions Workflow (Optional but Recommended)

Create `.github/workflows/deploy.yml` in your repository:

```yaml
name: Deploy Home Assistant Config

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Trigger GitOps Deployment
        env:
          WEBHOOK_SECRET: ${{ secrets.GITOPS_WEBHOOK_SECRET }}
        run: |
          COMMIT_MSG="$(git log -1 --pretty=%s)"
          COMMIT_SHA="$(git rev-parse --short HEAD)"

          # Create signed payload
          PAYLOAD=$(jq -cn \
            --arg ref "${{ github.ref }}" \
            --arg after "${{ github.sha }}" \
            --arg repo "${{ github.repository }}" \
            --arg message "$COMMIT_MSG" \
            --arg id "$COMMIT_SHA" \
            '{"ref":$ref,"after":$after,"repository":{"full_name":$repo},"head_commit":{"message":$message,"id":$id}}')

          # Calculate HMAC signature
          SIGNATURE=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | sed 's/^.* //')

          # Call webhook
          curl -X POST \
            -H "Content-Type: application/json" \
            -H "X-Hub-Signature-256: sha256=$SIGNATURE" \
            -H "X-GitHub-Event: push" \
            -d "$PAYLOAD" \
            http://your-home-assistant:8123/api/webhook/gitops-deploy
```

Add `GITOPS_WEBHOOK_SECRET` to your GitHub repository secrets.

## Configuration

### Basic Setup

1. Go to Settings → Devices & Services → Add Integration
2. Search for "GitOps"
3. Configure the integration:
   - **Webhook ID**: `gitops-deploy` (or custom ID)
   - **Infisical URL**: Leave default unless using self-hosted Infisical
   - **Infisical Client ID**: (Optional) For secrets management
   - **Infisical Client Secret**: (Optional) For secrets management
   - **Enable Drift Detection**: Enable to detect local configuration changes
   - **Drift Check Interval**: How often to check for drift (default: 300 seconds)

### Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| Webhook ID | Unique identifier for the deployment webhook | `gitops-deploy` |
| Webhook Secret | HMAC secret for signature verification | Auto-generated |
| Infisical URL | Infisical server URL (optional) | `https://app.infisical.com` |
| Infisical Client ID | Universal Auth client ID (optional) | - |
| Infisical Client Secret | Universal Auth client secret (optional) | - |
| Enable Drift Detection | Detect uncommitted local changes | `false` |
| Drift Check Interval | Seconds between drift checks | `300` |

## Usage

### Webhook Endpoint

Once configured, the integration creates a webhook endpoint:

```
http://your-home-assistant:8123/api/webhook/gitops-deploy
```

**Webhook Payload** (GitHub-compatible):

```json
{
  "ref": "refs/heads/main",
  "after": "commit-sha",
  "repository": {
    "full_name": "username/repo"
  },
  "head_commit": {
    "message": "Update configuration",
    "id": "short-sha"
  }
}
```

**Security**: The webhook validates HMAC-SHA256 signatures using the `X-Hub-Signature-256` header.

### Deployment Flow

1. **Push to Git** - Push configuration changes to your repository
2. **GitHub Actions Trigger** - Workflow sends signed webhook to Home Assistant
3. **Webhook Handler** - Integration validates signature and starts deployment
4. **Git Pull** - Fetches latest changes from repository
5. **Validation** - Runs `ha core check` to validate configuration
6. **Smart Reload** - Identifies changed files and reloads appropriate components
7. **Status Update** - Streams progress back via SSE (Server-Sent Events)

### Smart Component Reloading

The integration automatically reloads components based on changed files:

| Files Changed | Components Reloaded |
|---------------|---------------------|
| `automations.yaml` | Automations |
| `scripts.yaml` | Scripts |
| `groups.yaml` | Groups |
| `scenes.yaml` | Scenes |
| `configuration.yaml` | Multiple (group, template, input_*) |

**Restart Required**: Changes to `configuration.yaml`, `customize.yaml`, or `packages/*.yaml` will trigger a repair issue prompting for a manual restart.

### Sensors

The integration provides several sensors for monitoring:

- **`sensor.gitops_current_commit`** - Current deployed commit SHA and message
- **`sensor.gitops_latest_deployment`** - Last deployment timestamp and status
- **`sensor.gitops_git_status`** - Git repository status (clean, uncommitted changes, etc.)
- **`sensor.gitops_drift_status`** - Configuration drift status (enabled if drift detection is on)

### Update Entity

The integration creates an update entity that tracks when the integration itself has been updated. After updating the integration code via `git pull`, a repair issue will prompt you to reload the integration.

## Advanced Features

### Infisical Secrets Management (BETA)

The integration can sync secrets from Infisical and make them available to Home Assistant:

1. **Configure Infisical**:
   - Set up Universal Auth in Infisical
   - Get Client ID and Client Secret
   - Configure project ID, environment, and path

2. **Secrets Sync**:
   - Secrets are automatically synced on deployment
   - Written to `/config/secrets_infisical.yaml`
   - Automatically included in `/config/secrets.yaml`

3. **Webhook for Manual Refresh**:
   - Endpoint: `/api/webhook/gitops-secrets-refresh`
   - Manually trigger secrets sync via webhook

**Note**: Infisical integration is optional and in beta. The integration works perfectly without it.

### Drift Detection

When enabled, drift detection periodically checks for uncommitted local changes:

- Runs `git status` on configured interval
- Creates repair issues when drift is detected
- Helps identify UI-created automations or manual file edits
- Useful for keeping Git as the source of truth

## Troubleshooting

### Git Lock File Detected

If a deployment is interrupted (crash, restart), a git lock file may remain. The integration will create a repair issue with instructions to remove it:

```bash
rm /config/.git/index.lock
```

### Deployment Failed

Check the sensor attributes for error details:

```yaml
state: failed
attributes:
  error: "Git pull failed: ..."
  timestamp: "2024-01-01T12:00:00Z"
```

Common issues:
- SSH key not configured or expired
- Network connectivity to Git repository
- Merge conflicts in local repository
- Invalid YAML syntax

### SSH Authentication Issues

Verify SSH key setup:

```bash
# Check if key exists
ls -la /config/.ssh/id_ed25519

# Test GitHub connection
ssh -T git@github.com

# Verify git remote
git remote -v
```

### Component Reload Issues

If a component doesn't reload automatically:
- Check the `RELOAD_PATTERNS` in integration code
- Manually reload via Developer Tools → YAML → Reload (specific component)
- Check Home Assistant logs for errors

## Development

### Project Structure

```
homeassistant-gitops/
├── custom_components/
│   └── gitops/
│       ├── __init__.py          # Integration setup
│       ├── config_flow.py       # Configuration UI
│       ├── const.py             # Constants and defaults
│       ├── coordinator.py       # Core deployment logic
│       ├── sensor.py            # Sensor entities
│       ├── update.py            # Update entity
│       ├── manifest.json        # Integration manifest
│       ├── strings.json         # UI strings
│       └── translations/
│           └── en.json          # English translations
├── hacs.json                    # HACS manifest
├── info.md                      # HACS store description
├── README.md                    # This file
└── LICENSE                      # License file
```

### Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

### Testing

Test the integration in your development environment:

1. Copy to `custom_components/gitops/`
2. Restart Home Assistant
3. Enable debug logging:
   ```yaml
   logger:
     default: info
     logs:
       custom_components.gitops: debug
   ```
4. Check logs for detailed operation

## Support

- **Issues**: [GitHub Issues](https://github.com/jxnix-labs/homeassistant-gitops/issues)
- **Discussions**: [GitHub Discussions](https://github.com/jxnix-labs/homeassistant-gitops/discussions)

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Acknowledgments

Built with ❤️ for the Home Assistant community. Inspired by modern GitOps practices and the need for better configuration management in Home Assistant.
