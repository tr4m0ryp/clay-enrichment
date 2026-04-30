#!/usr/bin/env bash
# deploy.sh -- run on the GCP VM (e.g. searxng-v2) by the operator via
#   gcloud compute ssh <vm> --zone=europe-west1-b --command="/opt/clay-enrichment/deploy.sh"
#
# Pulls latest code, refreshes Python + Node deps, rebuilds the Next.js
# bundle, installs / refreshes the clay-key-* systemd timers, and restarts
# clay-web. Safe to re-run -- every step is idempotent.
set -euo pipefail

REPO_DIR=${REPO_DIR:-/opt/clay-enrichment}
cd "$REPO_DIR"

echo "[1/6] git pull ..."
git pull --ff-only

echo "[2/6] pip install -r requirements.txt ..."
./.venv/bin/pip install -r requirements.txt

echo "[3/6] npm install + next build ..."
cd web
npm install
npm run build
cd "$REPO_DIR"

echo "[4/6] installing/refreshing systemd units ..."
sudo cp -u systemd/clay-key-scrape.service \
           systemd/clay-key-scrape.timer \
           systemd/clay-key-validate.service \
           systemd/clay-key-validate.timer \
           systemd/clay-key-revalidate.service \
           systemd/clay-key-revalidate.timer \
           systemd/clay-key-recovery.service \
           systemd/clay-key-recovery.timer \
           /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now \
    clay-key-scrape.timer \
    clay-key-validate.timer \
    clay-key-revalidate.timer \
    clay-key-recovery.timer

echo "[5/6] installing pipeline-restart sudoers rule ..."
sudo install -m 0440 -o root -g root \
    systemd/clay-restart.sudoers /etc/sudoers.d/clay-restart

echo "[6/6] restarting clay-web ..."
sudo systemctl restart clay-web

echo "done."
