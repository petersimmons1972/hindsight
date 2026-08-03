#!/usr/bin/env bash
# Attacks on the containment check itself.  Each case builds a fresh sandbox,
# runs the tool with --apply, and reports (a) exit status, (b) whether anything
# was written outside the consumer root, (c) whether the printed UPDATED path
# equals the path that actually changed on disk.
set -u
WT="${1:-/home/psimmons/.claude/jobs/2c17b6f5/tmp/wt-r3-audit}"
MARK='<!-- hindsight: vendored failure-mode catalog -->'

case_run() {
  local name="$1" setup="$2"
  BASE="$(mktemp -d /tmp/hs-pb.XXXXXX)"; export BASE
  mkdir -p "$BASE/outside"
  printf 'OUTSIDE-SECRET\n' > "$BASE/outside/canary.md"
  PROJECT=''
  "$setup"                      # must set PROJECT and create it
  printf '%s\n' "$PROJECT" > "$BASE/consumers.txt"
  echo "=============== CASE: $name"
  echo "  consumers.txt (od): $(od -c "$BASE/consumers.txt" | head -3 | tr '\n' '|')"
  # snapshot everything under BASE except the consumer root
  before="$(find "$BASE" -type f -printf '%p\t%s\n' | sort | sha256sum)"
  out_before="$(find "$BASE/outside" -type f -printf '%p %s ' 2>/dev/null; sha256sum "$BASE/outside/canary.md" 2>/dev/null)"
  bash "$WT/bin/sync-failure-modes.sh" --apply --consumers "$BASE/consumers.txt" 2>&1 | sed 's/^/  | /'
  rc=${PIPESTATUS[0]}
  echo "  EXIT=$rc"
  out_after="$(find "$BASE/outside" -type f -printf '%p %s ' 2>/dev/null; sha256sum "$BASE/outside/canary.md" 2>/dev/null)"
  if [ "$out_before" = "$out_after" ]; then echo "  OUTSIDE: unchanged"
  else echo "  OUTSIDE: *** CHANGED ***"; echo "    before: $out_before"; echo "    after : $out_after"; fi
  echo "  catalog-sized files anywhere under BASE:"
  find "$BASE" -type f -size +100k -printf '    %s %p\n' 2>/dev/null | sed 's/$//'
  echo
}

# ---- prefix confusion: sibling root whose name is a string prefix extension ----
c_prefix() {
  mkdir -p "$BASE/x/consumer/docs" "$BASE/x/consumer-evil/docs/vendor/hindsight"
  ln -s "$BASE/x/consumer-evil/docs/vendor" "$BASE/x/consumer/docs/vendor"
  printf '%s\nEVIL-SIBLING\n' "$MARK" > "$BASE/x/consumer-evil/docs/vendor/hindsight/failure-modes.md"
  PROJECT="$BASE/x/consumer"
}
# ---- ..-traversal that lands back inside the root ----
c_dotdot_inside() {
  mkdir -p "$BASE/consumer/docs/other/hindsight"
  ln -s "../other" "$BASE/consumer/docs/vendor"
  PROJECT="$BASE/consumer"
}
# ---- consumer path given with embedded ..  ----
c_dotdot_arg() { mkdir -p "$BASE/consumer/docs"; PROJECT="$BASE/outside/../consumer"; }
# ---- bounce: component symlink -> outside dir -> symlink back inside ----
c_bounce() {
  mkdir -p "$BASE/consumer/docs" "$BASE/consumer/real/hindsight" "$BASE/outside/bounce"
  ln -s "$BASE/outside/bounce" "$BASE/consumer/docs/vendor"
  ln -s "$BASE/consumer/real/hindsight" "$BASE/outside/bounce/hindsight"
  PROJECT="$BASE/consumer"
}
# ---- spaces / newline / backslash / unicode / leading dash in the root name ----
c_space()    { PROJECT="$BASE/con sumer dir"; mkdir -p "$PROJECT/docs"; }
c_newline()  { PROJECT="$BASE/con
sumer";      mkdir -p "$PROJECT/docs"; }
c_trailnl()  { PROJECT="$BASE/consumer
";           mkdir -p "$PROJECT/docs"; mkdir -p "$BASE/consumer/docs/vendor/hindsight"
              printf 'DECOY-SIBLING\n' > "$BASE/consumer/docs/vendor/hindsight/failure-modes.md"; }
c_backslash(){ PROJECT="$BASE/con\\sumer"; mkdir -p "$PROJECT/docs"; }
c_unicode()  { PROJECT="$BASE/cönsumer-日本-🙂"; mkdir -p "$PROJECT/docs"; }
c_dash()     { PROJECT="$BASE/-consumer";  mkdir -p "$PROJECT/docs"; }
c_glob()     { PROJECT="$BASE/con*sumer";  mkdir -p "$PROJECT/docs"; }
# ---- root shapes ----
c_missing()  { PROJECT="$BASE/nope"; }
c_isfile()   { PROJECT="$BASE/afile"; printf 'x\n' > "$PROJECT"; }
c_dangling() { PROJECT="$BASE/dead"; ln -s "$BASE/no/such/place" "$PROJECT"; }
c_rootlink() { mkdir -p "$BASE/outside/realroot/docs"; PROJECT="$BASE/rootlink"; ln -s "$BASE/outside/realroot" "$PROJECT"; }
# ---- very deep nesting ----
c_deep() {
  local d="$BASE/consumer"; mkdir -p "$d"
  local i; for i in $(seq 1 60); do d="$d/lvl$i"; done; mkdir -p "$d/docs"
  PROJECT="$d"
}
# ---- clean baseline: honest write + honest reporting ----
c_clean()    { mkdir -p "$BASE/consumer/docs"; PROJECT="$BASE/consumer"; }

case_run "prefix-confusion sibling consumer-evil"      c_prefix
case_run "..-traversal landing back inside root"       c_dotdot_inside
case_run "consumer path containing .."                 c_dotdot_arg
case_run "bounce: outside dir symlinked back inside"   c_bounce
case_run "root name with spaces"                       c_space
case_run "root name with embedded newline"             c_newline
case_run "root name with TRAILING newline + decoy sibling" c_trailnl
case_run "root name with backslash"                    c_backslash
case_run "root name with unicode"                      c_unicode
case_run "root name with leading dash"                 c_dash
case_run "root name with glob metachars"               c_glob
case_run "consumer root missing"                       c_missing
case_run "consumer root is a regular file"             c_isfile
case_run "consumer root is a dangling symlink"         c_dangling
case_run "consumer root is a symlink to a real dir"    c_rootlink
case_run "very deep nesting (60 levels)"               c_deep
case_run "clean baseline"                              c_clean
