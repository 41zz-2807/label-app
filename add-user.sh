#!/usr/bin/env bash
# Kelola pengguna aplikasi cetak label lewat CLI di dalam container.
#
#   ./add-user.sh add andri          # tambah pengguna (menanyakan kata sandi)
#   ./add-user.sh list               # daftar pengguna
#   ./add-user.sh passwd andri       # ganti kata sandi (mengakhiri semua sesinya)
#   ./add-user.sh del andri          # hapus pengguna (templat & datanya tidak ikut terhapus)
#
# Kata sandi dibaca di dalam container, jadi tidak pernah lewat argument (tidak muncul di
# riwayat shell / process list). Butuh terminal interaktif untuk add/passwd.

set -euo pipefail
cd "$(dirname "$0")"

SERVICE="${SERVICE:-label-app}"
COMPOSE=(docker compose)

c_g=$'\033[32m'; c_y=$'\033[33m'; c_r=$'\033[31m'; c_0=$'\033[0m'
die() { echo "${c_r}Error:${c_0} $*" >&2; exit 1; }
info() { echo "${c_g}==${c_0} $*"; }
warn() { echo "${c_y}!${c_0} $*"; }

need_compose() {
  command -v docker >/dev/null 2>&1 || die "docker tidak ditemukan di PATH."
  "${COMPOSE[@]}" version >/dev/null 2>&1 || die "'docker compose' tidak bisa dipakai."
}

running() {
  local id
  id="$("${COMPOSE[@]}" ps --status running -q "$SERVICE" 2>/dev/null || true)"
  [ -n "$id" ]
}

require_running() {
  need_compose
  if ! running; then
    warn "Container '$SERVICE' sedang tidak jalan."
    echo "  Jalankan dulu:  docker compose up -d --build"
    die "Container '$SERVICE' belum jalan."
  fi
}

interactive() {
  [ -t 0 ] && [ -t 1 ] || die "Perintah ini butuh terminal interaktif (menanyakan kata sandi)."
}

usage() {
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Contoh:
  ./add-user.sh add andri
  ./add-user.sh list
EOF
}

cmd_list() {
  require_running
  info "Pengguna terdaftar"
  "${COMPOSE[@]}" exec -T "$SERVICE" python server.py --list-users
}

cmd_add() {
  local name="${1:-}"
  [ -n "$name" ] || { usage; die "Nama pengguna belum ditulis."; }
  require_running
  interactive
  info "Menambah pengguna '$name' (kata sandi minimal 6 karakter)"
  "${COMPOSE[@]}" exec "$SERVICE" python server.py --add-user "$name"
}

cmd_passwd() {
  local name="${1:-}"
  [ -n "$name" ] || { usage; die "Nama pengguna belum ditulis."; }
  require_running
  interactive
  info "Mengganti kata sandi '$name'"
  warn "Semua sesi aktif pengguna ini akan dikeluarkan."
  "${COMPOSE[@]}" exec "$SERVICE" python server.py --set-password "$name"
}

cmd_del() {
  local name="${1:-}"
  [ -n "$name" ] || { usage; die "Nama pengguna belum ditulis."; }
  require_running
  local answer=""
  printf "Hapus pengguna '%s'? (y/N) " "$name"
  read -r answer
  case "$answer" in
    y|Y|ya|YA) ;;
    *) echo "Dibatalkan."; return 0 ;;
  esac
  info "Menghapus '$name'"
  "${COMPOSE[@]}" exec -T "$SERVICE" python server.py --del-user "$name"
}

cmd_passwords() {
  # hati-hati: hanya menampilkan kata sandi acak yang belum pernah dipakai
  require_running
  warn "Kata sandi acak pengguna pertama hanya tampil sekali, di log:"
  echo "   ${COMPOSE[@]} logs | grep -A3 'Pengguna admin'"
}

sub="${1:-}"
[ $# -gt 0 ] && shift || true
case "$sub" in
  add)          cmd_add "${1:-}" ;;
  list|ls)      cmd_list ;;
  passwd|set)   cmd_passwd "${1:-}" ;;
  del|remove)   cmd_del "${1:-}" ;;
  passwords)    cmd_passwords ;;
  ""|-h|--help|help) usage ;;
  *) echo "Perintah tidak dikenal: '$sub'"; echo; usage; exit 1 ;;
esac