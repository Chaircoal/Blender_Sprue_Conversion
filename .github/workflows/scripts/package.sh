set -euo pipefail

VERSION="${1:?usage: $0 <version>}"
NAME="sprue_conv"
OSES=(windows linux)

# Fail if LFS pointer files slipped through
if grep -rlq "git-lfs.github.com/spec" wheels/ 2>/dev/null; then
  echo "ERROR: LFS pointer files found; wheels were not pulled" >&2
  exit 1
fi

mkdir -p dist
for target in "${OSES[@]}"; do
  excludes=(".git/*" ".github/*" "dist/*")
  for other in "${OSES[@]}"; do
    [[ "$other" != "$target" ]] && excludes+=("wheels/$other/*")
  done

  out="dist/$NAME-$VERSION-$target.zip"
  rm -f "$out"
  zip -r -q "$out" . -x "${excludes[@]}"
  echo "Built $out"
done
