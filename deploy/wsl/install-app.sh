#!/bin/bash
set -euo pipefail

if [[ $EUID != 0 || $# != 1 ]]; then
    echo 'Usage (as root): install-app.sh /path/to/app.tar.gz' >&2
    exit 1
fi
# Initial installation only. Keep the live state outside the application folder.
if [[ -f /opt/catsbot/app/main.py ]]; then
    echo 'An application is already installed; stop it and back up before updating.' >&2
    exit 1
fi
tar -xzf "$1" -C /opt/catsbot/app --no-same-owner
chown -R root:root /opt/catsbot/app
chmod -R u=rwX,go=rX /opt/catsbot/app
/opt/catsbot/venv/bin/python -m pip install -r /opt/catsbot/app/requirements.txt
/opt/catsbot/venv/bin/python -m pip freeze > /opt/catsbot/requirements-installed.txt
ln -s /var/lib/catsbot/data /opt/catsbot/app/data
ln -s /var/lib/catsbot/workspaces /opt/catsbot/app/workspaces
ln -s /var/lib/catsbot/.env /opt/catsbot/app/.env
ln -s /var/log/catsbot/bot.log /opt/catsbot/app/bot.log
echo 'Application installed. Copy state and environment before enabling the service.'
