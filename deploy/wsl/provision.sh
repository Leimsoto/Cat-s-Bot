#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

if [[ $EUID != 0 || $# != 1 ]]; then
    echo 'Usage (as root): provision.sh /path/to/deployment-files' >&2
    exit 1
fi
files=$(realpath "$1")

cat > /etc/apt/apt.conf.d/99catsbot-network <<'EOF'
Acquire::ForceIPv4 "true";
Acquire::http::Timeout "20";
Acquire::https::Timeout "20";
Acquire::Retries "2";
APT::Update::Error-Mode "any";
EOF

apt-get update
apt-get install -y --no-install-recommends ca-certificates python3 python3-venv \
    ffmpeg libopus0 systemd systemd-sysv dbus dbus-user-session logrotate tzdata
apt-get upgrade -y

if ! id catsbot >/dev/null 2>&1; then
    useradd --system --create-home --home-dir /var/lib/catsbot --shell /bin/bash catsbot
fi
install -d -m 0755 /opt/catsbot/app
install -d -o catsbot -g catsbot -m 0700 /var/lib/catsbot/data /var/lib/catsbot/workspaces /var/log/catsbot
install -m 0644 "$files/catsbot.service" /etc/systemd/system/catsbot.service
install -m 0755 "$files/keepalive.sh" /usr/local/sbin/catsbot-keepalive

cat > /etc/wsl.conf <<'EOF'
[boot]
systemd=true

[network]
hostname=catsbot

[user]
default=catsbot

[interop]
enabled=false
appendWindowsPath=false
EOF

cat > /etc/logrotate.d/catsbot <<'EOF'
/var/log/catsbot/bot.log {
    daily
    maxsize 20M
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    su catsbot catsbot
}
EOF

install -d -m 0755 /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/catsbot.conf <<'EOF'
[Journal]
Storage=persistent
SystemMaxUse=200M
MaxRetentionSec=14day
EOF
ln -sf /usr/share/zoneinfo/Europe/Lisbon /etc/localtime
printf '%s\n' Europe/Lisbon > /etc/timezone

python3 -m venv /opt/catsbot/venv
/opt/catsbot/venv/bin/python -m pip install --upgrade pip
# Enable only during cutover, after the old process has stopped and data is copied.
echo "Provisioning complete; Cat's Bot has not been started."
