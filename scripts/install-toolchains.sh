#!/usr/bin/env bash
# Installs the language toolchains that the setup-* actions and the Ubuntu runner image do not
# already provide. Safe to re-run; every step is best-effort, because `python3 -m harness doctor`
# reports what is missing and the harness simply skips languages whose toolchain is absent.
set -uo pipefail

KOTLIN_VERSION="${KOTLIN_VERSION:-2.1.20}"
SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"
export DEBIAN_FRONTEND=noninteractive

have() { command -v "$1" >/dev/null 2>&1; }
warn() { echo "::warning::$*"; }
add_path() {
  export PATH="$1:$PATH"
  [ -n "${GITHUB_PATH:-}" ] && echo "$1" >> "$GITHUB_PATH"
  return 0
}

# ---- apt packages ---------------------------------------------------------
pkgs=()
have gcc       || pkgs+=(build-essential)
have g++       || pkgs+=(build-essential)
have gfortran  || pkgs+=(gfortran)
have ruby      || pkgs+=(ruby)
have php       || pkgs+=(php-cli)
have perl      || pkgs+=(perl)
have lua5.4    || pkgs+=(lua5.4)
have Rscript   || pkgs+=(r-base-core)
have ghc       || pkgs+=(ghc)
have ocamlfind || pkgs+=(ocaml-nox ocaml-findlib)
have unzip     || pkgs+=(unzip)
have rustc     || pkgs+=(rustc)
if [ "${#pkgs[@]}" -gt 0 ]; then
  echo "apt: installing ${pkgs[*]}"
  { $SUDO apt-get update -qq && $SUDO apt-get install -y -qq --no-install-recommends "${pkgs[@]}"; } \
    || warn "apt-get install failed for: ${pkgs[*]}"
fi

# ---- Kotlin (JetBrains compiler release) ----------------------------------
if ! have kotlinc; then
  echo "kotlin: installing $KOTLIN_VERSION"
  if curl -fsSL "https://github.com/JetBrains/kotlin/releases/download/v${KOTLIN_VERSION}/kotlin-compiler-${KOTLIN_VERSION}.zip" -o /tmp/kotlin.zip \
     && mkdir -p "$HOME/.local" && unzip -q -o /tmp/kotlin.zip -d "$HOME/.local"; then
    add_path "$HOME/.local/kotlinc/bin"
  else
    warn "could not install Kotlin $KOTLIN_VERSION"
  fi
fi

# ---- Scala 3 via scala-cli ------------------------------------------------
if ! have scala-cli; then
  echo "scala-cli: installing"
  mkdir -p "$HOME/.local/bin"
  if curl -fsSL "https://github.com/VirtusLab/scala-cli/releases/latest/download/scala-cli-x86_64-pc-linux.gz" | gzip -d > "$HOME/.local/bin/scala-cli" \
     && chmod +x "$HOME/.local/bin/scala-cli"; then
    add_path "$HOME/.local/bin"
  else
    warn "could not install scala-cli"
  fi
fi

echo "toolchain install finished"
