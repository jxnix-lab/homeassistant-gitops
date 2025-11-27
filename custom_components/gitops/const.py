"""Constants for the GitOps Integration."""

DOMAIN = "gitops"

# Configuration keys
CONF_WEBHOOK_ID = "webhook_id"
CONF_WEBHOOK_SECRET = "webhook_secret"
CONF_SECRETS_WEBHOOK_ID = "secrets_webhook_id"
CONF_SECRETS_WEBHOOK_SECRET = "secrets_webhook_secret"
CONF_INFISICAL_URL = "infisical_url"
CONF_INFISICAL_CLIENT_ID = "infisical_client_id"
CONF_INFISICAL_CLIENT_SECRET = "infisical_client_secret"
CONF_INFISICAL_PROJECT_ID = "infisical_project_id"
CONF_INFISICAL_ENVIRONMENT = "infisical_environment"
CONF_INFISICAL_PATH = "infisical_path"
CONF_ENABLE_DRIFT_DETECTION = "enable_drift_detection"
CONF_DRIFT_CHECK_INTERVAL = "drift_check_interval"

# Defaults
DEFAULT_WEBHOOK_ID = "gitops-deploy"
DEFAULT_SECRETS_WEBHOOK_ID = "gitops-secrets-refresh"
DEFAULT_INFISICAL_URL = "https://app.infisical.com"
DEFAULT_INFISICAL_ENVIRONMENT = "prod"
DEFAULT_INFISICAL_PATH = "/"
DEFAULT_DRIFT_CHECK_INTERVAL = 300  # 5 minutes

# Repair issue IDs
REPAIR_GIT_LOCK = "git_lock_detected"
REPAIR_RESTART_REQUIRED = "restart_required"
REPAIR_INFISICAL_CONNECTION = "infisical_connection_failed"
REPAIR_GIT_CONNECTION = "git_connection_failed"

# Sensor entity IDs
SENSOR_CURRENT_COMMIT = "sensor.gitops_current_commit"
SENSOR_LATEST_DEPLOYMENT = "sensor.gitops_latest_deployment"
SENSOR_GIT_STATUS = "sensor.gitops_git_status"
SENSOR_DRIFT_STATUS = "sensor.gitops_drift_status"

# Deployment states
STATE_IDLE = "idle"
STATE_DEPLOYING = "deploying"
STATE_VALIDATING = "validating"
STATE_RELOADING = "reloading"
STATE_SUCCESS = "success"
STATE_FAILED = "failed"
STATE_RESTART_REQUIRED = "restart_required"

# File patterns for smart reload
RELOAD_PATTERNS = {
    "group": ["groups.yaml", "configuration.yaml"],
    "automation": ["automations.yaml", "automations/*.yaml"],
    "script": ["scripts.yaml", "scripts/*.yaml"],
    "scene": ["scenes.yaml", "scenes/*.yaml"],
    "input_boolean": ["configuration.yaml"],
    "input_select": ["configuration.yaml"],
    "input_text": ["configuration.yaml"],
    "input_number": ["configuration.yaml"],
    "input_datetime": ["configuration.yaml"],
    "template": ["configuration.yaml", "templates/*.yaml"],
}

# Files requiring full restart
RESTART_REQUIRED_PATTERNS = [
    "configuration.yaml",
    "customize.yaml",
    "packages/*.yaml",
]
