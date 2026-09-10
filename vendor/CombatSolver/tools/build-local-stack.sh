#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "$script_dir/.." && pwd)"
configuration="Release"

usage() {
    cat <<'EOF'
Usage: build-local-stack.sh [options]

Options:
  -c, --configuration NAME  Debug or Release (default: Release)
  -h, --help                Show this help
EOF
}

die() {
    echo "build-local-stack.sh: $*" >&2
    exit 2
}

while (($# > 0)); do
    case "$1" in
        -c|--configuration)
            (($# >= 2)) || die "missing value for $1"
            configuration="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown argument: $1"
            ;;
    esac
done

case "$configuration" in
    Debug|Release) ;;
    *) die "configuration must be Debug or Release: $configuration" ;;
esac

command -v dotnet >/dev/null 2>&1 || {
    echo "build-local-stack.sh: dotnet is required" >&2
    exit 1
}

dotnet build "$repository_root/CombatSolver.csproj" \
    --configuration "$configuration" \
    --nologo
