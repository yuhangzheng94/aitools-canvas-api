#!/bin/bash

# UV Grader Wrapper
# Executes Python graders running in separate uv virtual environments
# Handles directory changes, signal forwarding, and error conditions
#
# Usage: ./uv_grader_wrapper.sh [project_path] [grader_script]
# Environment: GRADER_PROJECT_PATH, GRADER_SCRIPT, UV_GRADER_DEBUG

set -euo pipefail

# Default configuration
DEFAULT_PROJECT_PATH="../aitools-discussion-grader"
DEFAULT_GRADER_SCRIPT="discussion-grader/canvas_speedgrader.py"

# Global variables
CHILD_PID=""
ORIGINAL_DIR="$(pwd)"

# Debug logging function
debug_log() {
    if [[ "${UV_GRADER_DEBUG:-0}" == "1" ]]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] DEBUG: $*" >&2
    fi
}

# Error logging function  
error_log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
}

# Info logging function
info_log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: $*" >&2
}

# Cleanup function
cleanup() {
    debug_log "Cleanup function called"
    
    # Kill child process if it exists
    if [[ -n "$CHILD_PID" ]]; then
        debug_log "Terminating child process $CHILD_PID"
        if kill -0 "$CHILD_PID" 2>/dev/null; then
            kill -TERM "$CHILD_PID" 2>/dev/null || true
            sleep 1
            if kill -0 "$CHILD_PID" 2>/dev/null; then
                debug_log "Force killing child process $CHILD_PID"
                kill -KILL "$CHILD_PID" 2>/dev/null || true
            fi
        fi
        wait "$CHILD_PID" 2>/dev/null || true
    fi
    
    # Return to original directory
    if [[ -d "$ORIGINAL_DIR" ]]; then
        cd "$ORIGINAL_DIR"
        debug_log "Returned to original directory: $ORIGINAL_DIR"
    fi
}

# Signal handlers
handle_sigint() {
    debug_log "Received SIGINT (Ctrl+C)"
    info_log "Interrupted by user"
    cleanup
    exit 130
}

handle_sigterm() {
    debug_log "Received SIGTERM"
    info_log "Terminated"
    cleanup
    exit 143
}

# Setup signal traps
trap handle_sigint SIGINT
trap handle_sigterm SIGTERM
trap cleanup EXIT

# Help function
show_help() {
    cat << EOF
UV Grader Wrapper - Execute Python graders in separate uv environments

USAGE:
    $0 [PROJECT_PATH] [GRADER_SCRIPT]

ARGUMENTS:
    PROJECT_PATH    Path to the grader project directory
                    Default: $DEFAULT_PROJECT_PATH
                    Can also set via GRADER_PROJECT_PATH environment variable
    
    GRADER_SCRIPT   Relative path to grader script within project
                    Default: $DEFAULT_GRADER_SCRIPT
                    Can also set via GRADER_SCRIPT environment variable

ENVIRONMENT VARIABLES:
    GRADER_PROJECT_PATH    Override default project path
    GRADER_SCRIPT         Override default grader script
    UV_GRADER_DEBUG=1     Enable debug output

EXAMPLES:
    # Use defaults
    $0
    
    # Specify project path
    $0 /path/to/grader/project
    
    # Specify both path and script
    $0 /path/to/project custom-grader.py
    
    # Use environment variables
    GRADER_PROJECT_PATH=/path/to/project $0
    
    # Debug mode
    UV_GRADER_DEBUG=1 $0

EXIT CODES:
    0    Success
    1    Invalid arguments or usage
    2    Project path does not exist or is not accessible
    3    uv command not found
    4    Grader script does not exist or is not readable
    130  Interrupted by user (Ctrl+C)
    143  Terminated by SIGTERM

EOF
}

# Parse arguments
PROJECT_PATH=""
GRADER_SCRIPT=""

case "${1:-}" in
    -h|--help|help)
        show_help
        exit 0
        ;;
    "")
        # No arguments - use environment or defaults
        PROJECT_PATH="${GRADER_PROJECT_PATH:-$DEFAULT_PROJECT_PATH}"
        GRADER_SCRIPT="${GRADER_SCRIPT:-$DEFAULT_GRADER_SCRIPT}"
        ;;
    *)
        # At least one argument provided
        PROJECT_PATH="${1:-${GRADER_PROJECT_PATH:-$DEFAULT_PROJECT_PATH}}"
        GRADER_SCRIPT="${2:-${GRADER_SCRIPT:-$DEFAULT_GRADER_SCRIPT}}"
        ;;
esac

debug_log "Starting UV Grader Wrapper"
debug_log "Project path: $PROJECT_PATH"
debug_log "Grader script: $GRADER_SCRIPT"
debug_log "Original directory: $ORIGINAL_DIR"

# Validation: Check project path
if [[ ! -d "$PROJECT_PATH" ]]; then
    error_log "Project path does not exist: $PROJECT_PATH"
    exit 2
fi

if [[ ! -r "$PROJECT_PATH" ]]; then
    error_log "Project path is not readable: $PROJECT_PATH"
    exit 2
fi

# Validation: Check uv command
if ! command -v uv >/dev/null 2>&1; then
    error_log "uv command not found in PATH"
    error_log "Please install uv: https://docs.astral.sh/uv/"
    exit 3
fi

debug_log "uv command found: $(command -v uv)"

# Change to project directory
debug_log "Changing to project directory: $PROJECT_PATH"
cd "$PROJECT_PATH"

# Validation: Check grader script exists
if [[ ! -f "$GRADER_SCRIPT" ]]; then
    error_log "Grader script does not exist: $PROJECT_PATH/$GRADER_SCRIPT"
    exit 4
fi

if [[ ! -r "$GRADER_SCRIPT" ]]; then
    error_log "Grader script is not readable: $PROJECT_PATH/$GRADER_SCRIPT"
    exit 4
fi

debug_log "Grader script found: $PROJECT_PATH/$GRADER_SCRIPT"

# Check if there's a uv environment in this project
if [[ -f "pyproject.toml" ]]; then
    debug_log "Found pyproject.toml - this appears to be a uv project"
elif [[ -f ".python-version" ]] || [[ -d ".venv" ]]; then
    debug_log "Found Python environment indicators"
else
    debug_log "Warning: No obvious Python environment indicators found"
fi

# Execute the grader using uv
debug_log "Executing: uv run python $GRADER_SCRIPT"
debug_log "Working directory: $(pwd)"

# Clear any existing VIRTUAL_ENV to avoid conflicts with uv
unset VIRTUAL_ENV
debug_log "Cleared VIRTUAL_ENV to avoid uv environment conflicts"

# Start the grader process (run in foreground to preserve stdin)
debug_log "Starting grader process"
uv run python "$GRADER_SCRIPT"
EXIT_CODE=$?

debug_log "Child process exited with code: $EXIT_CODE"

# Reset CHILD_PID since the process has finished
CHILD_PID=""

# Return to original directory
cd "$ORIGINAL_DIR"
debug_log "Returned to original directory: $ORIGINAL_DIR"

debug_log "UV Grader Wrapper completed successfully"
exit $EXIT_CODE
