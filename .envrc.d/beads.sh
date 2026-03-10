# Install/update beads (bd) to ~/.local/bin from GitHub releases
# Checks for updates once per day on direnv reload

_beads_arch() {
  case "$(uname -m)" in
    x86_64)        echo "amd64" ;;
    aarch64|arm64) echo "arm64" ;;
    *) echo "unsupported" ;;
  esac
}

_beads_os() {
  case "$(uname -s)" in
    Linux)  echo "linux" ;;
    Darwin) echo "darwin" ;;
    *) echo "unsupported" ;;
  esac
}

_beads_latest_version() {
  curl -fsSL https://api.github.com/repos/steveyegge/beads/releases/latest 2>/dev/null \
    | sed -n 's/.*"tag_name": *"v\{0,1\}\([^"]*\)".*/\1/p' | head -1
}

_beads_install() {
  local version=$1
  local os=$(_beads_os)
  local arch=$(_beads_arch)
  local asset="beads_${version}_${os}_${arch}.tar.gz"
  local url="https://github.com/steveyegge/beads/releases/download/v${version}/${asset}"

  echo "beads: installing v${version}..."
  local tmpdir
  tmpdir=$(mktemp -d)
  if curl -fsSL "$url" | tar xz -C "$tmpdir"; then
    mkdir -p "$HOME/.local/bin"
    mv "$tmpdir/bd" "$HOME/.local/bin/bd"
    ln -sf bd "$HOME/.local/bin/beads"
    echo "beads: v${version} installed to ~/.local/bin/bd"
  else
    echo "beads: failed to download $asset"
  fi
  rm -rf "$tmpdir"
}

_beads_ensure() {
  local bin="$HOME/.local/bin/bd"
  local stamp="$HOME/.local/share/beads/.update-check"
  mkdir -p "$HOME/.local/share/beads"

  if [[ ! -x "$bin" ]]; then
    local latest=$(_beads_latest_version)
    [[ -n "$latest" ]] && _beads_install "$latest"
  elif [[ ! -f "$stamp" ]] || [[ -n $(find "$stamp" -mtime +1 2>/dev/null) ]]; then
    local current
    current=$("$bin" --version 2>/dev/null | sed -n 's/.*\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -1)
    local latest=$(_beads_latest_version)
    if [[ -n "$latest" && "$current" != "$latest" ]]; then
      echo "beads: $current -> $latest"
      _beads_install "$latest"
    fi
    touch "$stamp"
  fi
}

_beads_ensure
PATH_add "$HOME/.local/bin"
