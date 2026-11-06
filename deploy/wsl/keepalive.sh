#!/bin/sh
set -eu

# An attached WSL process keeps the distribution alive after systemd starts.
# This exits with wsl.exe when the distribution is stopped; Windows relaunches it.
systemctl start catsbot.service
exec sleep infinity
