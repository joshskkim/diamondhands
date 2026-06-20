#!/bin/sh
# Render Alertmanager's config from env at startup, then exec the binary.
#
# Why a script: Alertmanager does not expand env vars in its config file, and we refuse to
# commit SMTP secrets. So we template the config here from ALERT_SMTP_* env vars (kept in the
# host .env, gitignored). Alerting is OPT-IN: with no ALERT_SMTP_SMARTHOST set we render a
# 'null' receiver so Alertmanager starts cleanly and simply drops notifications, instead of
# crash-looping on an incomplete email config. Mirrors how AI/Stripe stay dark until keyed.
set -e

CONFIG=/tmp/alertmanager.yml

if [ -n "${ALERT_SMTP_SMARTHOST}" ]; then
  cat > "$CONFIG" <<EOF
global:
  smtp_smarthost: '${ALERT_SMTP_SMARTHOST}'
  smtp_from: '${ALERT_SMTP_FROM}'
  smtp_auth_username: '${ALERT_SMTP_USERNAME}'
  smtp_auth_password: '${ALERT_SMTP_PASSWORD}'
  smtp_require_tls: ${ALERT_SMTP_REQUIRE_TLS:-true}

route:
  receiver: email
  group_by: ['alertname']
  group_wait: 30s
  group_interval: 5m
  # Re-send a still-firing alert at most this often, so a lingering issue keeps nagging.
  repeat_interval: 4h

receivers:
  - name: email
    email_configs:
      - to: '${ALERT_SMTP_TO}'
        send_resolved: true
EOF
  echo "alertmanager: email receiver configured (-> ${ALERT_SMTP_TO})"
else
  cat > "$CONFIG" <<'EOF'
route:
  receiver: 'null'
receivers:
  - name: 'null'
EOF
  echo "alertmanager: ALERT_SMTP_SMARTHOST unset — alerts will NOT be delivered (null receiver)"
fi

exec /bin/alertmanager --config.file="$CONFIG" --storage.path=/alertmanager
