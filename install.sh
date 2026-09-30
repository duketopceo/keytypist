#!/bin/sh
set -eu

REPO=/home/lukedaduke/Documents/github/personal/keytypist

if [ "$(id -u)" -ne 0 ]; then
    exec pkexec "$0" "$@"
fi

cp "$REPO/keytypist-wpm.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now keytypist-wpm

echo "keytypist-wpm installed and started."
echo "  status:  systemctl status keytypist-wpm"
echo "  stop:    systemctl stop keytypist-wpm"
echo "  start:   systemctl start keytypist-wpm"
echo "  restart: systemctl restart keytypist-wpm"
