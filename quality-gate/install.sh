#!/bin/bash
# =============================================================================
# Quality Gate Installer
# =============================================================================
# One-command installation for any codebase.
#
# Usage:
#   ./quality-gate/install.sh           # Full install
#   ./quality-gate/install.sh --hooks   # Git hooks only
#   ./quality-gate/install.sh --ci      # CI workflows only
#   ./quality-gate/install.sh --check   # Verify installation
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$PROJECT_ROOT" ]; then
    PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
fi

# =============================================================================
# FUNCTIONS
# =============================================================================

check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check Python
    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
        log_success "Python 3 found: $(python3 --version)"
    elif command -v python &> /dev/null; then
        PYTHON_CMD="python"
        log_success "Python found: $(python --version)"
    else
        log_error "Python not found. Please install Python 3.10+"
        exit 1
    fi

    # Require Python 3.10+ (quality_gate.py uses modern syntax)
    if ! "$PYTHON_CMD" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)'; then
        log_error "Python 3.10+ required. Detected: $("$PYTHON_CMD" --version 2>&1)"
        exit 1
    fi

    # Check Git
    if command -v git &> /dev/null; then
        log_success "Git found: $(git --version)"
    else
        log_error "Git not found. Please install Git."
        exit 1
    fi

    # Check if in git repo
    if git rev-parse --git-dir > /dev/null 2>&1; then
        log_success "Git repository detected"
    else
        log_error "Not in a git repository. Run 'git init' first."
        exit 1
    fi
}

install_git_hooks() {
    log_info "Installing git hooks..."

    HOOKS_DIR="$PROJECT_ROOT/.git/hooks"
    mkdir -p "$HOOKS_DIR"

    # Path from git root to this quality-gate folder (supports monorepos)
    QG_DIR_REL="$("$PYTHON_CMD" -c "import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))" "$SCRIPT_DIR" "$PROJECT_ROOT")"

    # Pre-commit hook
    cat > "$HOOKS_DIR/pre-commit" << HOOK
#!/bin/bash
# Quality Gate Pre-Commit Hook

echo "[Quality Gate] Running pre-commit checks..."

# Pick a Python interpreter
PYTHON_BIN="python3"
command -v "\$PYTHON_BIN" >/dev/null 2>&1 || PYTHON_BIN="python"

# Run quality gate on staged files
if [ -f "${QG_DIR_REL}/quality_gate.py" ]; then
    "\$PYTHON_BIN" "${QG_DIR_REL}/quality_gate.py" --staged
    if [ \$? -ne 0 ]; then
        echo ""
        echo "[X] Quality Gate FAILED. Fix the issues above before committing."
        echo ""
        exit 1
    fi
fi

# Run TypeScript check if applicable
if command -v npx >/dev/null 2>&1 && [ -f "package.json" ] && grep -q "typescript" package.json 2>/dev/null; then
    echo "[Quality Gate] Running TypeScript check..."
    npx tsc --noEmit 2>/dev/null || {
        echo "[X] TypeScript check failed. Fix type errors before committing."
        exit 1
    }
fi

echo "[OK] Quality Gate passed"
exit 0
HOOK
    chmod +x "$HOOKS_DIR/pre-commit"
    log_success "Pre-commit hook installed"

    # Pre-push hook
    cat > "$HOOKS_DIR/pre-push" << HOOK
#!/bin/bash
# Quality Gate Pre-Push Hook

echo "[Quality Gate] Running pre-push checks (strict mode)..."

# Pick a Python interpreter
PYTHON_BIN="python3"
command -v "\$PYTHON_BIN" >/dev/null 2>&1 || PYTHON_BIN="python"

# Run quality gate in strict mode
if [ -f "${QG_DIR_REL}/quality_gate.py" ]; then
    "\$PYTHON_BIN" "${QG_DIR_REL}/quality_gate.py" --strict
    if [ \$? -ne 0 ]; then
        echo ""
        echo "[X] Quality Gate FAILED (strict). Fix all warnings before pushing."
        echo ""
        exit 1
    fi
fi

echo "[OK] Quality Gate passed (strict)"
exit 0
HOOK
    chmod +x "$HOOKS_DIR/pre-push"
    log_success "Pre-push hook installed"

    # Commit-msg hook
    cat > "$HOOKS_DIR/commit-msg" << HOOK
#!/bin/bash
# Quality Gate Commit Message Hook

PYTHON_BIN="python3"
command -v "\$PYTHON_BIN" >/dev/null 2>&1 || PYTHON_BIN="python"

if [ -f "${QG_DIR_REL}/check_commit_msg.py" ]; then
    "\$PYTHON_BIN" "${QG_DIR_REL}/check_commit_msg.py" "\$1"
    exit \$?
fi
exit 0
HOOK
    chmod +x "$HOOKS_DIR/commit-msg"
    log_success "Commit-msg hook installed"
}

install_ci_workflows() {
    log_info "Installing CI workflows..."

    # GitHub Actions
    if [ -d ".github" ] || [ ! -d ".gitlab" ]; then
        mkdir -p "$PROJECT_ROOT/.github/workflows"
        if [ -f "$SCRIPT_DIR/workflows/quality-gate.yml" ]; then
            cp "$SCRIPT_DIR/workflows/quality-gate.yml" "$PROJECT_ROOT/.github/workflows/"
            log_success "GitHub Actions workflow installed"
        else
            log_warn "GitHub Actions workflow template not found"
        fi
    fi

    # GitLab CI (if .gitlab-ci.yml exists, append; otherwise skip)
    if [ -f "$PROJECT_ROOT/.gitlab-ci.yml" ]; then
        log_info "GitLab CI detected. Add the following to your .gitlab-ci.yml:"
        echo ""
        echo "quality-gate:"
        echo "  stage: test"
        echo "  script:"
        echo "    - python quality-gate/quality_gate.py --strict"
        echo ""
    fi
}

install_vscode_integration() {
    log_info "Setting up VS Code integration..."

    mkdir -p "$PROJECT_ROOT/.vscode"

    # Tasks
    cat > "$PROJECT_ROOT/.vscode/tasks.json" << 'JSON'
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Quality Gate",
      "type": "shell",
      "command": "python",
      "args": ["quality-gate/quality_gate.py", "--verbose"],
      "group": "test",
      "presentation": {
        "reveal": "always",
        "panel": "new"
      },
      "problemMatcher": []
    },
    {
      "label": "Quality Gate (Strict)",
      "type": "shell",
      "command": "python",
      "args": ["quality-gate/quality_gate.py", "--strict", "--verbose"],
      "group": "test",
      "presentation": {
        "reveal": "always",
        "panel": "new"
      },
      "problemMatcher": []
    }
  ]
}
JSON
    log_success "VS Code tasks configured"
}

update_gitignore() {
    log_info "Updating .gitignore..."

    GITIGNORE="$PROJECT_ROOT/.gitignore"

    # Entries to add
    ENTRIES=(
        ""
        "# Quality Gate"
        ".quality-reports/"
        "quality-report.json"
    )

    # Check if already present
    if grep -q "Quality Gate" "$GITIGNORE" 2>/dev/null; then
        log_info ".gitignore already has Quality Gate entries"
        return
    fi

    # Append entries
    for entry in "${ENTRIES[@]}"; do
        echo "$entry" >> "$GITIGNORE"
    done

    log_success ".gitignore updated"
}

verify_installation() {
    log_info "Verifying installation..."

    ERRORS=0

    # Check quality gate script
    if [ -f "$PROJECT_ROOT/quality-gate/quality_gate.py" ]; then
        log_success "quality_gate.py exists"
    else
        log_error "quality_gate.py not found"
        ((ERRORS++))
    fi

    # Check config
    if [ -f "$PROJECT_ROOT/quality-gate/quality-gate.config.json" ]; then
        log_success "quality-gate.config.json exists"
    else
        log_error "quality-gate.config.json not found"
        ((ERRORS++))
    fi

    # Check git hooks
    if [ -x "$PROJECT_ROOT/.git/hooks/pre-commit" ]; then
        log_success "pre-commit hook installed"
    else
        log_warn "pre-commit hook not installed"
    fi

    # Test quality gate
    log_info "Running quality gate test..."
    $PYTHON_CMD "$PROJECT_ROOT/quality-gate/quality_gate.py" --help > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        log_success "quality_gate.py runs successfully"
    else
        log_error "quality_gate.py failed to run"
        ((ERRORS++))
    fi

    if [ $ERRORS -eq 0 ]; then
        echo ""
        log_success "Installation complete! Quality Gate is ready."
        echo ""
        echo "Next steps:"
        echo "  1. Review quality-gate/quality-gate.config.json"
        echo "  2. Customize rules for your project"
        echo "  3. Run: python quality-gate/quality_gate.py"
        echo ""
    else
        log_error "Installation had $ERRORS error(s)"
        exit 1
    fi
}

print_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --hooks    Install git hooks only"
    echo "  --ci       Install CI workflows only"
    echo "  --check    Verify installation"
    echo "  --help     Show this help"
    echo ""
    echo "Default: Full installation (hooks + CI + VS Code)"
}

# =============================================================================
# MAIN
# =============================================================================

main() {
    echo ""
    echo "=============================================="
    echo "  Quality Gate Installer"
    echo "=============================================="
    echo ""

    case "${1:-full}" in
        --hooks)
            check_prerequisites
            install_git_hooks
            ;;
        --ci)
            install_ci_workflows
            ;;
        --check)
            check_prerequisites
            verify_installation
            ;;
        --help)
            print_usage
            ;;
        full|"")
            check_prerequisites
            install_git_hooks
            install_ci_workflows
            install_vscode_integration
            update_gitignore
            verify_installation
            ;;
        *)
            log_error "Unknown option: $1"
            print_usage
            exit 1
            ;;
    esac
}

main "$@"
