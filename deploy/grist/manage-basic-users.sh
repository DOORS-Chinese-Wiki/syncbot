#!/usr/bin/env bash
set -euo pipefail

PASSWD_FILE="${PASSWD_FILE:-/www/server/nginx/conf/.grist_htpasswd}"

usage() {
  cat <<'EOF'
Usage:
  manage-basic-users.sh add ACCOUNT
  manage-basic-users.sh remove ACCOUNT
  manage-basic-users.sh list

ACCOUNT may be an email address or a distributed username.
Passwords are read interactively and are not accepted as command arguments.
After an account change, Nginx is tested and reloaded automatically.
EOF
}

reload_nginx() {
  nginx -t
  nginx -s reload
}

case "${1:-}" in
  add)
    [[ $# -eq 2 ]] || { usage; exit 2; }
    email="$2"
    [[ "$email" =~ ^[^:[:space:]]+$ ]] || {
      echo "Account name cannot contain spaces or colons." >&2
      exit 2
    }
    read -r -s -p "Password for $email: " password
    echo
    read -r -s -p "Repeat password: " password2
    echo
    [[ -n "$password" && "$password" == "$password2" ]] || {
      echo "Passwords are empty or do not match." >&2
      exit 2
    }
    hash="$(printf '%s' "$password" | openssl passwd -apr1 -stdin)"
    umask 027
    touch "$PASSWD_FILE"
    chown root:www "$PASSWD_FILE"
    chmod 640 "$PASSWD_FILE"
    temp="$(mktemp "${PASSWD_FILE}.XXXXXX")"
    trap 'rm -f "$temp"' EXIT
    awk -v email="$email" 'index($0, email ":") != 1' "$PASSWD_FILE" > "$temp"
    printf '%s:%s\n' "$email" "$hash" >> "$temp"
    install -o root -g www -m 640 "$temp" "$PASSWD_FILE"
    reload_nginx
    echo "Account added or updated: $email"
    ;;
  remove)
    [[ $# -eq 2 ]] || { usage; exit 2; }
    email="$2"
    [[ -f "$PASSWD_FILE" ]] || exit 0
    umask 027
    temp="$(mktemp "${PASSWD_FILE}.XXXXXX")"
    trap 'rm -f "$temp"' EXIT
    awk -v email="$email" 'index($0, email ":") != 1' "$PASSWD_FILE" > "$temp"
    install -o root -g www -m 640 "$temp" "$PASSWD_FILE"
    reload_nginx
    echo "Account removed: $email"
    ;;
  list)
    [[ -f "$PASSWD_FILE" ]] || exit 0
    cut -d: -f1 "$PASSWD_FILE" | sort
    ;;
  *)
    usage
    exit 2
    ;;
esac
