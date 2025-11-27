# GitOps for Home Assistant

## Automated Configuration Deployment with Git

GitOps brings modern GitOps principles to Home Assistant, enabling automated configuration deployments triggered by Git pushes. Push your configuration changes to GitHub, and watch them deploy automatically to your Home Assistant instance with intelligent component reloading and comprehensive deployment tracking.

### Key Features

- **🚀 Automated Deployments** - Push to Git → Auto-deploy to HA
- **🔒 Secure Webhooks** - HMAC-SHA256 signature verification
- **🎯 Smart Reloads** - Automatically reloads only changed components
- **📊 Real-time Status** - SSE streaming of deployment progress
- **🔄 Drift Detection** - Detect and alert on configuration drift
- **📈 Deployment Tracking** - Sensors for commit SHA, deployment status, and more
- **🔐 Infisical Integration** - Optional secrets management (BETA)
- **⚡ Crash Recovery** - Automatic detection and recovery from interrupted deployments

### Perfect For

- Managing Home Assistant configuration as code
- Multi-environment deployments (dev, staging, prod)
- Teams collaborating on HA configurations
- Keeping configuration in sync across instances
- Maintaining deployment history and rollback capability

### GitHub Actions Integration

Works seamlessly with GitHub Actions workflows to trigger deployments on push, with real-time deployment progress streamed back to your CI/CD pipeline.

See the [README](https://github.com/jxnix-labs/homeassistant-gitops) for full documentation and setup instructions.
