# Install/update dolt to ~/.local/bin from GitHub releases
# Checks for updates once per day on direnv reload

_dolt_arch() {
  case "$(uname -m)" in
    x86_64)        echo "amd64" ;;
    aarch64|arm64) echo "arm64" ;;
    *) echo "unsupported" ;;
  esac
}

_dolt_os() {
  case "$(uname -s)" in
    Linux)  echo "linux" ;;
    Darwin) echo "darwin" ;;
    *) echo "unsupported" ;;
  esac
}

_dolt_latest_version() {
  curl -fsSL https://api.github.com/repos/dolthub/dolt/releases/latest 2>/dev/null \
    | sed -n 's/.*"tag_name": *"v\{0,1\}\([^"]*\)".*/\1/p' | head -1
}

_dolt_install() {
  local version=$1
  local os=$(_dolt_os)
  local arch=$(_dolt_arch)
  local url="https://github.com/dolthub/dolt/releases/download/v${version}/dolt-${os}-${arch}.tar.gz"

  echo "dolt: installing v${version}..."
  local tmpdir
  tmpdir=$(mktemp -d)
  if curl -fsSL "$url" | tar xz -C "$tmpdir"; then
    mkdir -p "$HOME/.local/bin"
    mv "$tmpdir/dolt-${os}-${arch}/bin/dolt" "$HOME/.local/bin/dolt"
    echo "dolt: v${version} installed to ~/.local/bin/dolt"
  else
    echo "dolt: failed to download"
  fi
  rm -rf "$tmpdir"
}

_dolt_ensure() {
  local bin="$HOME/.local/bin/dolt"
  local stamp="$HOME/.local/share/dolt/.update-check"
  mkdir -p "$HOME/.local/share/dolt"

  if [[ ! -x "$bin" ]]; then
    local latest=$(_dolt_latest_version)
    [[ -n "$latest" ]] && _dolt_install "$latest"
  elif [[ ! -f "$stamp" ]] || [[ -n $(find "$stamp" -mtime +1 2>/dev/null) ]]; then
    local current
    current=$("$bin" version 2>/dev/null | sed -n 's/.*\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -1)
    local latest=$(_dolt_latest_version)
    if [[ -n "$latest" && "$current" != "$latest" ]]; then
      echo "dolt: $current -> $latest"
      _dolt_install "$latest"
    fi
    touch "$stamp"
  fi
}

_dolt_ensure
PATH_add "$HOME/.local/bin"
