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

run_as_root() {
  if [ "$(id -u)" = "0" ]; then
    "$@"
  elif has_command sudo; then
    sudo "$@"
  elif has_command doas; then
    doas "$@"
  else
    die "Installing system packages needs sudo, doas, or a root shell."
  fi
}

refresh_homebrew_path() {
  if [ -x "/opt/homebrew/bin/brew" ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [ -x "/usr/local/bin/brew" ]; then
    eval "$(/usr/local/bin/brew shellenv)"
  elif [ -x "/home/linuxbrew/.linuxbrew/bin/brew" ]; then
    eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
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
    die "Homebrew is needed to automatically install Git, Python, and ffmpeg on macOS."
  fi

  has_command brew || die "Homebrew installed, but brew is not available in this terminal. Close Terminal, open it again, and rerun this script."
}

python_venv_ok() {
  has_command python3 && python3 -c 'import venv' >/dev/null 2>&1
}

system_dependencies_ok() {
  has_command git && has_command python3 && python_venv_ok && has_command ffmpeg && has_command ffprobe
}

ensure_macos_dependencies() {
  ensure_homebrew

  missing=""

  if ! has_command git; then
    missing="$missing git"
  fi

  if ! has_command python3 || ! python_venv_ok; then
    missing="$missing python"
  fi

  if ! has_command ffmpeg || ! has_command ffprobe; then
    missing="$missing ffmpeg"
  fi

  if [ -n "$missing" ]; then
    say "Installing missing system dependencies with Homebrew:$missing"
    brew install $missing || die "Homebrew failed to install required dependencies."
    refresh_homebrew_path
  fi
}

detect_linux_package_manager() {
  if has_command apt-get; then
    printf '%s\n' apt
  elif has_command dnf; then
    printf '%s\n' dnf
  elif has_command yum; then
    printf '%s\n' yum
  elif has_command pacman; then
    printf '%s\n' pacman
  elif has_command zypper; then
    printf '%s\n' zypper
  elif has_command apk; then
    printf '%s\n' apk
  elif has_command xbps-install; then
    printf '%s\n' xbps
  elif has_command emerge; then
    printf '%s\n' emerge
  elif has_command nix-env; then
    printf '%s\n' nix
  elif has_command brew; then
    printf '%s\n' brew
  else
    printf '%s\n' ""
  fi
}

linux_packages_for_manager() {
  case "$1" in
    apt) printf '%s\n' "git python3 python3-venv python3-pip ffmpeg" ;;
    dnf) printf '%s\n' "git python3 python3-pip ffmpeg" ;;
    yum) printf '%s\n' "git python3 python3-pip ffmpeg" ;;
    pacman) printf '%s\n' "git python python-pip ffmpeg" ;;
    zypper) printf '%s\n' "git python3 python3-pip python3-virtualenv ffmpeg" ;;
    apk) printf '%s\n' "git python3 py3-pip py3-virtualenv ffmpeg" ;;
    xbps) printf '%s\n' "git python3 python3-pip python3-virtualenv ffmpeg" ;;
    emerge) printf '%s\n' "dev-vcs/git dev-lang/python media-video/ffmpeg" ;;
    nix) printf '%s\n' "nixpkgs.git nixpkgs.python312 nixpkgs.ffmpeg" ;;
    brew) printf '%s\n' "git python ffmpeg" ;;
    *) printf '%s\n' "" ;;
  esac
}

install_linux_packages() {
  manager="$1"
  packages=$(linux_packages_for_manager "$manager")
  [ -n "$packages" ] || die "Unsupported Linux package manager. Install Git, Python 3 with venv, pip, ffmpeg, and ffprobe manually."

  say "Installing or refreshing system dependencies with $manager: $packages"

  case "$manager" in
    apt)
      run_as_root apt-get update
      run_as_root apt-get install -y $packages
      ;;
    dnf)
      run_as_root dnf install -y $packages
      ;;
    yum)
      run_as_root yum install -y $packages
      ;;
    pacman)
      run_as_root pacman -Sy --needed --noconfirm $packages
      ;;
    zypper)
      run_as_root zypper --non-interactive install $packages
      ;;
    apk)
      run_as_root apk add --no-cache $packages
      ;;
    xbps)
      run_as_root xbps-install -Sy $packages
      ;;
    emerge)
      run_as_root emerge --ask=n $packages
      ;;
    nix)
      nix-env -iA $packages
      ;;
    brew)
      brew install $packages
      refresh_homebrew_path
      ;;
    *)
      die "Unsupported Linux package manager."
      ;;
  esac
}

ensure_linux_dependencies() {
  refresh_homebrew_path

  if system_dependencies_ok; then
    return 0
  fi

  manager=$(detect_linux_package_manager)
  [ -n "$manager" ] || die "No supported Linux package manager found. Install Git, Python 3 with venv, pip, ffmpeg, and ffprobe manually."

  if yes_or_no "Install missing Linux system dependencies with $manager now?"; then
    install_linux_packages "$manager"
  else
    die "Git, Python 3 with venv, ffmpeg, and ffprobe are required."
  fi
}

ensure_system_dependencies() {
  os_name=$(uname -s 2>/dev/null || printf '%s' unknown)

  case "$os_name" in
    Darwin)
      ensure_macos_dependencies
      ;;
    Linux)
      ensure_linux_dependencies
      ;;
    *)
      die "Unsupported OS: $os_name. Use the Windows PowerShell installer or manual install instructions."
      ;;
  esac

  has_command git || die "Git is still missing. Close the terminal, open it again, and rerun this script."
  has_command python3 || die "Python 3 is still missing. Close the terminal, open it again, and rerun this script."
  python_venv_ok || die "Python venv support is still missing. Install the Python venv package for your distribution and rerun this script."
  has_command ffmpeg || die "ffmpeg is still missing. Some Linux distributions require an extra multimedia repository. Install ffmpeg manually and rerun this script."
  has_command ffprobe || die "ffprobe is still missing. Some Linux distributions require an extra multimedia repository. Install ffmpeg manually and rerun this script."
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
