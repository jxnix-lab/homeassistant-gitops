"""Constants for the GitOps Integration."""

DOMAIN = "gitops"

# Configuration keys
CONF_DOPPLER_SERVICE_TOKEN = "doppler_service_token"
CONF_DOPPLER_API_URL = "doppler_api_url"
CONF_UPDATE_CHECK_INTERVAL = "update_check_interval"
CONF_ENABLE_DRIFT_DETECTION = "enable_drift_detection"
CONF_DRIFT_CHECK_INTERVAL = "drift_check_interval"

# Defaults
DEFAULT_DOPPLER_API_URL = "https://api.doppler.com"
DEFAULT_UPDATE_CHECK_INTERVAL = 300  # 5 minutes
DEFAULT_DRIFT_CHECK_INTERVAL = 300  # 5 minutes

# Repair issue IDs
REPAIR_GIT_LOCK = "git_lock_detected"
REPAIR_RESTART_REQUIRED = "restart_required"
REPAIR_DOPPLER_CONNECTION = "doppler_connection_failed"
REPAIR_GIT_CONNECTION = "git_connection_failed"

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
