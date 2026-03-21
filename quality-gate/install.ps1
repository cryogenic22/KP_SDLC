# =============================================================================
# Quality Gate Installer (Windows PowerShell)
# =============================================================================
# One-command installation for any codebase.
#
# Usage:
#   .\quality-gate\install.ps1           # Full install
#   .\quality-gate\install.ps1 -Hooks    # Git hooks only
#   .\quality-gate\install.ps1 -CI       # CI workflows only
#   .\quality-gate\install.ps1 -Check    # Verify installation
# =============================================================================

param(
    [switch]$Hooks,
    [switch]$CI,
    [switch]$Check,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

# Colors
function Write-Info { Write-Host "[INFO] " -ForegroundColor Blue -NoNewline; Write-Host $args }
function Write-Success { Write-Host "[OK] " -ForegroundColor Green -NoNewline; Write-Host $args }
function Write-Warn { Write-Host "[WARN] " -ForegroundColor Yellow -NoNewline; Write-Host $args }
function Write-Error { Write-Host "[ERROR] " -ForegroundColor Red -NoNewline; Write-Host $args }

# Get paths
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
try {
    $ProjectRoot = (git rev-parse --show-toplevel 2>$null).Trim()
} catch {
    $ProjectRoot = Split-Path -Parent $ScriptDir
}

$QualityGateRel = [IO.Path]::GetRelativePath($ProjectRoot, $ScriptDir) -replace '\\', '/'

# =============================================================================
# FUNCTIONS
# =============================================================================

function Test-Prerequisites {
    Write-Info "Checking prerequisites..."

    # Check Python
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $version = & python --version 2>&1
        Write-Success "Python found: $version"
        $script:PythonCmd = "python"
    } else {
        $python3 = Get-Command python3 -ErrorAction SilentlyContinue
        if ($python3) {
            $version = & python3 --version 2>&1
            Write-Success "Python found: $version"
            $script:PythonCmd = "python3"
        } else {
            Write-Error "Python not found. Please install Python 3.10+"
            exit 1
        }
    }

    # Require Python 3.10+ (quality_gate.py uses modern syntax)
    try {
        $ver = & $script:PythonCmd -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"
        $parts = $ver.Trim().Split('.')
        $maj = [int]$parts[0]
        $min = [int]$parts[1]
        if ($maj -lt 3 -or ($maj -eq 3 -and $min -lt 10)) {
            Write-Error "Python $ver detected. Please upgrade to Python 3.10+."
            exit 1
        }
    } catch {
        Write-Warn "Unable to verify Python version; proceeding."
    }

    # Check Git
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) {
        $version = & git --version 2>&1
        Write-Success "Git found: $version"
    } else {
        Write-Error "Git not found. Please install Git."
        exit 1
    }

    # Check if in git repo
    try {
        git rev-parse --git-dir 2>&1 | Out-Null
        Write-Success "Git repository detected"
    } catch {
        Write-Error "Not in a git repository. Run 'git init' first."
        exit 1
    }
}

function Install-GitHooks {
    Write-Info "Installing git hooks..."

    $HooksDir = Join-Path $ProjectRoot ".git\hooks"
    New-Item -ItemType Directory -Force -Path $HooksDir | Out-Null

    # Pre-commit hook
    $PreCommitContent = @'
#!/bin/bash
# Quality Gate Pre-Commit Hook

echo "[Quality Gate] Running pre-commit checks..."

# Run quality gate on staged files
if [ -f "{QG_DIR}/quality_gate.py" ]; then
    python "{QG_DIR}/quality_gate.py" --staged
    if [ $? -ne 0 ]; then
        echo ""
        echo "Quality Gate FAILED. Fix the issues above before committing."
        echo ""
        exit 1
    fi
fi

echo "Quality Gate passed"
exit 0
'@.Replace("{QG_DIR}", $QualityGateRel)
    Set-Content -Path (Join-Path $HooksDir "pre-commit") -Value $PreCommitContent -NoNewline
    Write-Success "Pre-commit hook installed"

    # Pre-push hook
    $PrePushContent = @'
#!/bin/bash
# Quality Gate Pre-Push Hook

echo "[Quality Gate] Running pre-push checks (strict mode)..."

if [ -f "{QG_DIR}/quality_gate.py" ]; then
    python "{QG_DIR}/quality_gate.py" --strict
    if [ $? -ne 0 ]; then
        echo ""
        echo "Quality Gate FAILED (strict). Fix all warnings before pushing."
        echo ""
        exit 1
    fi
fi

echo "Quality Gate passed (strict)"
exit 0
'@.Replace("{QG_DIR}", $QualityGateRel)
    Set-Content -Path (Join-Path $HooksDir "pre-push") -Value $PrePushContent -NoNewline
    Write-Success "Pre-push hook installed"

    # Commit-msg hook
    $CommitMsgContent = @'
#!/bin/bash
# Quality Gate Commit Message Hook

if [ -f "{QG_DIR}/check_commit_msg.py" ]; then
    python "{QG_DIR}/check_commit_msg.py" "$1"
    exit $?
fi
exit 0
'@.Replace("{QG_DIR}", $QualityGateRel)
    Set-Content -Path (Join-Path $HooksDir "commit-msg") -Value $CommitMsgContent -NoNewline
    Write-Success "Commit-msg hook installed"
}

function Install-CIWorkflows {
    Write-Info "Installing CI workflows..."

    # GitHub Actions
    $GithubDir = Join-Path $ProjectRoot ".github\workflows"
    New-Item -ItemType Directory -Force -Path $GithubDir | Out-Null

    $SourceWorkflow = Join-Path $ScriptDir "workflows\quality-gate.yml"
    if (Test-Path $SourceWorkflow) {
        Copy-Item $SourceWorkflow -Destination $GithubDir
        Write-Success "GitHub Actions workflow installed"
    } else {
        Write-Warn "GitHub Actions workflow template not found"
    }
}

function Install-VSCodeIntegration {
    Write-Info "Setting up VS Code integration..."

    $VSCodeDir = Join-Path $ProjectRoot ".vscode"
    New-Item -ItemType Directory -Force -Path $VSCodeDir | Out-Null

    $TasksContent = @'
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
      }
    },
    {
      "label": "Quality Gate (Strict)",
      "type": "shell",
      "command": "python",
      "args": ["quality-gate/quality_gate.py", "--strict", "--verbose"],
      "group": "test"
    }
  ]
}
'@
    Set-Content -Path (Join-Path $VSCodeDir "tasks.json") -Value $TasksContent
    Write-Success "VS Code tasks configured"
}

function Update-Gitignore {
    Write-Info "Updating .gitignore..."

    $GitignorePath = Join-Path $ProjectRoot ".gitignore"

    $Entries = @"

# Quality Gate
.quality-reports/
quality-report.json
"@

    if (Test-Path $GitignorePath) {
        $Content = Get-Content $GitignorePath -Raw
        if ($Content -match "Quality Gate") {
            Write-Info ".gitignore already has Quality Gate entries"
            return
        }
    }

    Add-Content -Path $GitignorePath -Value $Entries
    Write-Success ".gitignore updated"
}

function Test-Installation {
    Write-Info "Verifying installation..."

    $Errors = 0

    # Check quality gate script
    $QGPath = Join-Path $ProjectRoot "quality-gate\quality_gate.py"
    if (Test-Path $QGPath) {
        Write-Success "quality_gate.py exists"
    } else {
        Write-Error "quality_gate.py not found"
        $Errors++
    }

    # Check config
    $ConfigPath = Join-Path $ProjectRoot "quality-gate\quality-gate.config.json"
    if (Test-Path $ConfigPath) {
        Write-Success "quality-gate.config.json exists"
    } else {
        Write-Error "quality-gate.config.json not found"
        $Errors++
    }

    # Check git hooks
    $PreCommitPath = Join-Path $ProjectRoot ".git\hooks\pre-commit"
    if (Test-Path $PreCommitPath) {
        Write-Success "pre-commit hook installed"
    } else {
        Write-Warn "pre-commit hook not installed"
    }

    # Test quality gate
    Write-Info "Running quality gate test..."
    try {
        & $script:PythonCmd (Join-Path $ProjectRoot "quality-gate\quality_gate.py") --help 2>&1 | Out-Null
        Write-Success "quality_gate.py runs successfully"
    } catch {
        Write-Error "quality_gate.py failed to run"
        $Errors++
    }

    if ($Errors -eq 0) {
        Write-Host ""
        Write-Success "Installation complete! Quality Gate is ready."
        Write-Host ""
        Write-Host "Next steps:"
        Write-Host "  1. Review quality-gate\quality-gate.config.json"
        Write-Host "  2. Customize rules for your project"
        Write-Host "  3. Run: python quality-gate\quality_gate.py"
        Write-Host ""
    } else {
        Write-Error "Installation had $Errors error(s)"
        exit 1
    }
}

function Show-Usage {
    Write-Host "Usage: .\install.ps1 [OPTIONS]"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -Hooks    Install git hooks only"
    Write-Host "  -CI       Install CI workflows only"
    Write-Host "  -Check    Verify installation"
    Write-Host "  -Help     Show this help"
    Write-Host ""
    Write-Host "Default: Full installation (hooks + CI + VS Code)"
}

# =============================================================================
# MAIN
# =============================================================================

Write-Host ""
Write-Host "=============================================="
Write-Host "  Quality Gate Installer"
Write-Host "=============================================="
Write-Host ""

if ($Help) {
    Show-Usage
    exit 0
}

if ($Hooks) {
    Test-Prerequisites
    Install-GitHooks
} elseif ($CI) {
    Install-CIWorkflows
} elseif ($Check) {
    Test-Prerequisites
    Test-Installation
} else {
    # Full installation
    Test-Prerequisites
    Install-GitHooks
    Install-CIWorkflows
    Install-VSCodeIntegration
    Update-Gitignore
    Test-Installation
}
