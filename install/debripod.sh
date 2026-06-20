#!/usr/bin/env sh
set -eu

REPO_URL="https://github.com/JoeDoe56/Debripod.git"
BRANCH="main"
APP_DIR_NAME="debripod"
VENV_DIR=".debripod-venv"
PORT="8083"

say() {
  printf '%s\n' "$1"
}

die() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

has_command() {
  command -v "$1" >/dev/null 2>&1
}

yes_or_no() {
  prompt="$1"
  while true; do
    printf '%s [y/n]: ' "$prompt"
    read ans || return 1
    case "$(printf '%s' "$ans" | tr '[:upper:]' '[:lower:]')" in
      y|yes) return 0 ;;
      n|no) return 1 ;;
      *) say "Enter y or n." ;;
    esac
  done
}

refresh_homebrew_path() {
  if [ -x "/opt/homebrew/bin/brew" ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [ -x "/usr/local/bin/brew" ]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

ensure_homebrew() {
  refresh_homebrew_path

  if has_command brew; then
    return 0
  fi

  say "Homebrew is not installed."
  if yes_or_no "Install Homebrew now?"; then
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    refresh_homebrew_path
  else
    die "Homebrew is needed to automatically install Git, Python, and ffmpeg."
  fi

  has_command brew || die "Homebrew installed, but brew is not available in this terminal. Close Terminal, open it again, and rerun this script."
}

ensure_system_dependencies() {
  ensure_homebrew

  missing=""

  if ! has_command git; then
    missing="$missing git"
  fi

  if ! has_command python3; then
    missing="$missing python"
  fi

  if ! has_command ffmpeg || ! has_command ffprobe; then
    missing="$missing ffmpeg"
  fi

  if [ -n "$missing" ]; then
    say "Installing missing system dependencies:$missing"
    brew install $missing || die "Homebrew failed to install required dependencies."
    refresh_homebrew_path
  fi

  has_command git || die "Git is still missing. Close Terminal, open it again, and rerun this script."
  has_command python3 || die "Python 3 is still missing. Close Terminal, open it again, and rerun this script."
  has_command ffmpeg || die "ffmpeg is still missing. Close Terminal, open it again, and rerun this script."
  has_command ffprobe || die "ffprobe is still missing. Close Terminal, open it again, and rerun this script."
}

find_debripod_dir() {
  for path in ./*; do
    [ -d "$path" ] || continue
    name=$(basename "$path")
    lower=$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')
    if [ "$lower" = "debripod" ]; then
      printf '%s\n' "$path"
      return 0
    fi
  done
  return 1
}

ensure_config_port() {
  mkdir -p config

  if [ ! -f "config/debripod.local.json" ] && [ ! -f "config/debripod.json" ]; then
    cat > "config/debripod.local.json" <<EOF
{
  "PORT": $PORT
}
EOF
    say "Created config/debripod.local.json with port $PORT."
  else
    say "Existing config found. Leaving it unchanged."
  fi
}

ensure_venv() {
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    say "Creating Python virtual environment named debripod."
    python3 -m venv --prompt debripod "$VENV_DIR"
  fi

  . "$VENV_DIR/bin/activate"
  python -m pip install --upgrade pip setuptools wheel
}

install_python_dependencies() {
  say "Installing DebriPod Python dependencies."

  if [ -f "requirements.txt" ]; then
    python -m pip install -r requirements.txt
  fi

  python -m pip install -e .
}

check_updates() {
  say "Checking GitHub for DebriPod updates."

  if ! git fetch origin "$BRANCH"; then
    say "Could not check GitHub for updates. Starting the installed copy."
    return 0
  fi

  local_rev=$(git rev-parse HEAD)
  remote_rev=$(git rev-parse "origin/$BRANCH")

  if [ "$local_rev" = "$remote_rev" ]; then
    say "No DebriPod updates found."
    return 0
  fi

  dirty=$(git status --porcelain --untracked-files=no)
  if [ -n "$dirty" ]; then
    say "DebriPod has local tracked code changes."
    say "Skipping update so nothing is overwritten."
    return 0
  fi

  if yes_or_no "Updates are available. Pull them now?"; then
    git pull --ff-only origin "$BRANCH"
    ensure_system_dependencies
    install_python_dependencies
  else
    say "Skipping update."
  fi
}

start_app() {
  say "Starting DebriPod on http://127.0.0.1:$PORT"
  python -m debripod.app
}

ensure_system_dependencies

APP_DIR=""
if APP_DIR=$(find_debripod_dir); then
  say "Found existing DebriPod folder: $APP_DIR"
else
  say "No DebriPod folder found. Cloning main into ./$APP_DIR_NAME"
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR_NAME"
  APP_DIR="./$APP_DIR_NAME"
fi

cd "$APP_DIR"

if [ ! -d ".git" ]; then
  die "$APP_DIR is not a Git repository. Refusing to overwrite it."
fi

ensure_config_port
ensure_venv

if [ ! -f "$VENV_DIR/.debripod-deps-installed" ]; then
  install_python_dependencies
  date > "$VENV_DIR/.debripod-deps-installed"
else
  check_updates
fi

start_app
