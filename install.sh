#!/usr/bin/env bash
# Door station setup on Raspberry Pi OS (Debian 13 Trixie).
# Usage (as root):
#   ./install.sh               install or update (can be repeated any time)
#   ./install.sh backup  <file.tar.gz>
#   ./install.sh restore <file.tar.gz>
#   ./install.sh audio-info    show sound cards and control names
#   ./install.sh rfid-import <dir>   take over an existing Home Key pairing
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
PREFIX=/opt/doorstation
SRC="$PREFIX/src"
ETC="${DOORSTATION_ETC:-/etc/doorstation}"       # test environment: DOORSTATION_ETC
VAR="${DOORSTATION_VAR:-/var/lib/doorstation}"  # test environment: DOORSTATION_VAR
BOOT="${DOORSTATION_BOOT:-/boot/firmware}"
TIMESYNC_DIR="${DOORSTATION_TIMESYNC_DIR:-/etc/systemd/timesyncd.conf.d}"  # test environment
USER_UNIT_DIR="${DOORSTATION_USER_UNIT_DIR:-/etc/systemd/user}"  # test environment
SVC_USER=doorstation
RUN_TMP=""          # own temp directory per run, deleted on exit (passwords!)
WARNINGS=()
AUDIO_RESTARTED=0   # PipeWire restarted -> baresip and sound need new audio nodes

log() { echo "==> $*"; }

# Print a warning right away and once more in the summary at the end.
warn() { echo "WARNING: $*" >&2; WARNINGS+=("$*"); }

tmpfile() { mktemp -p "${RUN_TMP:-${TMPDIR:-/tmp}}"; }

# Abort with a message. Needed because functions in "&&" chains do not run under set -e.
die() { echo "ERROR: $*" >&2; exit 1; }

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "Please run as root: sudo $0 $*" >&2
    exit 1
  fi
}

# Copies $1 to $2 if the content differs. Exit 0 = changed, 1 = unchanged.
copy_if_changed() {
  local src="$1" dst="$2" mode="${3:-644}"
  if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
    return 1
  fi
  install -m "$mode" "$src" "$dst" || die "cannot write $dst"
  return 0
}

install_base() {
  log "Packages"
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
    mosquitto mosquitto-clients nftables python3-venv python3-libgpiod rsync >/dev/null

  log "User $SVC_USER"
  if ! id "$SVC_USER" >/dev/null 2>&1; then
    useradd --system --home "$VAR" --shell /usr/sbin/nologin "$SVC_USER"
  fi
  usermod -a -G gpio,dialout,audio "$SVC_USER"

  log "Directories"
  install -d -m 755 "$ETC" "$PREFIX" "$PREFIX/venv"
  # Only install.sh (root) reads the secrets; no service needs them at runtime.
  install -d -m 700 -o root -g root "$ETC/secrets"
  find "$ETC/secrets" -type f -exec chown root:root {} + -exec chmod 600 {} +
  install -d -m 755 -o "$SVC_USER" -g "$SVC_USER" "$VAR" "$VAR/sounds"

  log "Source code to $SRC"
  rsync -a --delete --exclude .git --exclude .venv --exclude .superpowers \
    --exclude __pycache__ --exclude '*.egg-info' "$REPO/" "$SRC/"
}

install_mosquitto() {
  log "Mosquitto (local)"
  local changed=0
  copy_if_changed "$SRC/deploy/mosquitto/doorstation.conf" /etc/mosquitto/conf.d/doorstation.conf && changed=1
  systemctl enable --quiet mosquitto
  if [ "$changed" -eq 1 ] || ! systemctl is-active --quiet mosquitto; then
    systemctl restart mosquitto
  fi
}

# install_python_package <name> <path> [--system-site-packages]
# Creates $PREFIX/venv/<name> and installs common and <path> into it.
# Exit 0 = code changed (restart the service), 1 = unchanged.
install_python_package() {
  local name="$1" path="$2" opt="${3:-}"
  local venv="$PREFIX/venv/$name"
  local stamp="$venv/.source-hash"
  local hash
  hash="$(cd "$SRC" && find common "${path#"$SRC"/}" -type f -not -path '*/tests/*' -not -path '*/build/*' \
    -not -path '*.egg-info/*' -not -path '*/__pycache__/*' -print0 \
    | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)"
  if [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$hash" ]; then
    return 1
  fi
  log "Python package $name"
  if [ ! -x "$venv/bin/python" ]; then
    # shellcheck disable=SC2086
    python3 -m venv $opt "$venv" || die "could not create venv $venv"
  fi
  "$venv/bin/pip" install -q --disable-pip-version-check --upgrade "$SRC/common" "$path" \
    || die "pip installation of $name failed"
  echo "$hash" > "$stamp"
  return 0
}

# install_config <service>: copy the example configuration only if none exists yet.
install_config() {
  local svc="$1"
  if [ ! -f "$ETC/$svc.yaml" ]; then
    log "Example configuration $ETC/$svc.yaml"
    install -m 644 "$SRC/config-examples/$svc.yaml" "$ETC/$svc.yaml"
  fi
}

# Reads a value from a flat YAML file (key: value).
yaml_value() {
  sed -nE "s/^$2:[[:space:]]*\"?([^\"#]*[^\"#[:space:]])\"?[[:space:]]*(#.*)?$/\1/p" "$1" | head -n1
}

# config_txt_add <file> <line>: make sure the line is in the [all] section so it applies to
# every Pi model (the file may otherwise end in [pi5] or similar). Exit 0 = added, 1 = present.
config_txt_add() {
  local file="$1" line="$2"
  if awk -v want="$line" '
      /^\[.*\]$/ { all = ($0 == "[all]"); next }
      all && $0 == want { found = 1 }
      END { exit !found }' all=1 "$file"; then
    return 1
  fi
  [ -z "$(tail -c1 "$file")" ] || echo >> "$file"
  if [ "$(awk '/^\[.*\]$/ { s = $0 } END { print (s == "" ? "[all]" : s) }' "$file")" != "[all]" ]; then
    echo "[all]" >> "$file"
  fi
  echo "$line" >> "$file"
}

# render_bridge <bridge.yaml> <password file> <target>: generate the bridge configuration.
# Values are validated instead of escaped - a special character would break the Mosquitto configuration.
render_bridge() {
  local cfg="$1" pwfile="$2" out="$3" host port user prefix pass
  host="$(yaml_value "$cfg" host)"; port="$(yaml_value "$cfg" port)"
  user="$(yaml_value "$cfg" username)"; prefix="$(yaml_value "$cfg" prefix)"
  prefix="${prefix:-doorstation}"
  [[ "$host" =~ ^[A-Za-z0-9.:-]+$ ]] || { echo "bridge.yaml: host '$host' invalid" >&2; return 1; }
  [[ "$port" =~ ^[0-9]{1,5}$ ]] || { echo "bridge.yaml: port '$port' invalid" >&2; return 1; }
  [[ "$user" =~ ^[A-Za-z0-9._@-]+$ ]] || { echo "bridge.yaml: username '$user' invalid" >&2; return 1; }
  [[ "$prefix" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "bridge.yaml: prefix '$prefix' invalid (no / + #)" >&2; return 1; }
  pass="$(head -n1 "$pwfile" | tr -d '\r')"
  [ -n "$pass" ] || { echo "bridge_password is empty" >&2; return 1; }
  sed -e "s|@HOST@|$host|" -e "s|@PORT@|$port|" -e "s|@USERNAME@|$user|" \
      -e "s|@PREFIX@|$prefix|g" "$SRC/deploy/mosquitto/bridge.conf.template" \
    | PW="$pass" awk '{ i = index($0, "@PASSWORD@"); if (i) $0 = substr($0, 1, i - 1) ENVIRON["PW"] substr($0, i + 10); print }' > "$out"
}

# apply_mosquitto_conf <new> <target>: apply the configuration and restart Mosquitto. If it does
# not start with it, the previous one is restored - without a broker the bell stays silent.
apply_mosquitto_conf() {
  local new="$1" dst="$2" backup=""
  if [ -f "$dst" ] && cmp -s "$new" "$dst"; then
    return 0
  fi
  if [ -f "$dst" ]; then
    backup="$(tmpfile)"; cp -p "$dst" "$backup"
  fi
  install -m 640 "$new" "$dst"; chown root:mosquitto "$dst"
  if systemctl restart mosquitto; then
    return 0
  fi
  warn "Mosquitto does not start with the new bridge configuration - previous one restored (journalctl -u mosquitto)"
  if [ -n "$backup" ]; then
    install -m 640 "$backup" "$dst"; chown root:mosquitto "$dst"
  else
    rm -f "$dst"
  fi
  systemctl restart mosquitto || warn "Mosquitto does not start with the previous configuration either"
  return 0
}

install_bridge() {
  local cfg="$ETC/bridge.yaml" pw="$ETC/secrets/bridge_password"
  local dst=/etc/mosquitto/conf.d/doorstation-bridge.conf tmp
  if [ ! -f "$cfg" ] || [ ! -s "$pw" ]; then
    if [ -f "$dst" ]; then
      log "Bridge removed (no configuration)"
      rm -f "$dst"
      systemctl restart mosquitto
    else
      log "Bridge: no configuration ($cfg, $pw) - skipped"
    fi
    return 0
  fi
  log "Bridge to the home automation"
  tmp="$(tmpfile)"
  if ! render_bridge "$cfg" "$pw" "$tmp"; then
    warn "Bridge not changed - check $cfg and the password"
  else
    apply_mosquitto_conf "$tmp" "$dst"
  fi
  rm -f "$tmp"
}

# install_unit <name>: install a systemd unit. Exit 0 = changed.
install_unit() {
  if copy_if_changed "$SRC/deploy/systemd/$1.service" "/etc/systemd/system/$1.service"; then
    systemctl daemon-reload
    return 0
  fi
  return 1
}

install_gpio() {
  local restart=0
  install_python_package gpio "$SRC/services/gpio" --system-site-packages && restart=1
  install_config gpio
  install_unit doorstation-gpio && restart=1
  systemctl enable --quiet doorstation-gpio
  if [ "$restart" -eq 1 ] || ! systemctl is-active --quiet doorstation-gpio; then
    log "(Re)starting doorstation-gpio"
    systemctl restart doorstation-gpio
  fi
}

REBOOT_NEEDED=0

# systemd user command for the service user (its user manager runs thanks to linger).
user_systemctl() {
  local uid; uid="$(id -u "$SVC_USER")"
  runuser -u "$SVC_USER" -- env XDG_RUNTIME_DIR="/run/user/$uid" systemctl --user "$@"
}

# install_audio_conf <file> <dir>: configuration file for the PipeWire/WirePlumber user service of
# $SVC_USER. Exit 0 = changed (restart PipeWire), 1 = unchanged.
install_audio_conf() {
  local src="$1" dir="$2" dst
  dst="$dir/$(basename "$src")"
  install -d -o "$SVC_USER" -g "$SVC_USER" "$VAR/.config" "$(dirname "$dir")" "$dir"
  copy_if_changed "$src" "$dst" || return 1
  chown "$SVC_USER:$SVC_USER" "$dst"
}

# remove_audio_conf <file>: drop a configuration file of earlier versions.
# Exit 0 = removed (restart PipeWire), 1 = not present.
remove_audio_conf() {
  [ -e "$1" ] || return 1
  rm -f "$1"
}

# PipeWire only for $SVC_USER: a login session (e.g. SSH) would start its own PipeWire,
# take over the sound card and set WirePlumber's default volumes (speaker 40 %).
# Takes effect with the next login. Exit 0 = changed, 1 = unchanged.
install_pipewire_service_user_only() {
  local unit tmp changed=1
  tmp="$(mktemp)"
  printf '%s\n' "# Door station: PipeWire only for the service user - another user session would take over" \
    "# the sound card and reset its volumes. Generated by install.sh." "[Unit]" "ConditionUser=$SVC_USER" >"$tmp"
  for unit in pipewire.service pipewire.socket pipewire-pulse.service pipewire-pulse.socket \
      wireplumber.service filter-chain.service; do
    install -d "$USER_UNIT_DIR/$unit.d"
    copy_if_changed "$tmp" "$USER_UNIT_DIR/$unit.d/doorstation.conf" && changed=0
  done
  rm -f "$tmp"
  return "$changed"
}

install_audio() {
  log "Audio (PipeWire with echo cancellation)"
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
    pipewire pipewire-alsa pipewire-bin wireplumber alsa-utils baresip-core >/dev/null \
    || die "could not install audio packages"
  loginctl enable-linger "$SVC_USER"
  local uid; uid="$(id -u "$SVC_USER")"
  local i; for i in $(seq 1 20); do [ -S "/run/user/$uid/bus" ] && break; sleep 0.5; done
  [ -S "/run/user/$uid/bus" ] || die "user manager of $SVC_USER is not running"
  local changed=0
  install_audio_conf "$SRC/deploy/pipewire/60-echo-cancel.conf" "$VAR/.config/pipewire/pipewire.conf.d" && changed=1
  install_audio_conf "$SRC/deploy/wireplumber/50-doorstation-alsa.conf" \
    "$VAR/.config/wireplumber/wireplumber.conf.d" && changed=1
  # Up to 2026-10: WirePlumber then set its default volumes on every restart.
  remove_audio_conf "$VAR/.config/wireplumber/wireplumber.conf.d/51-doorstation-volumes.conf" && changed=1
  install_pipewire_service_user_only && user_systemctl daemon-reload
  user_systemctl enable --quiet pipewire.socket pipewire wireplumber
  if [ "$changed" -eq 1 ]; then
    user_systemctl restart pipewire wireplumber
    AUDIO_RESTARTED=1
  else
    user_systemctl start pipewire wireplumber
  fi

  # Disable onboard audio (jack, HDMI): the USB stick is then the only audio device.
  local cfgtxt="$BOOT/config.txt"
  if [ -f "$cfgtxt" ]; then
    if grep -q '^dtparam=audio=on' "$cfgtxt"; then
      sed -i 's/^dtparam=audio=on/dtparam=audio=off/' "$cfgtxt"; REBOOT_NEEDED=1
    fi
    if grep -q '^dtoverlay=vc4-kms-v3d$' "$cfgtxt"; then
      sed -i 's/^dtoverlay=vc4-kms-v3d$/dtoverlay=vc4-kms-v3d,noaudio/' "$cfgtxt"; REBOOT_NEEDED=1
    fi
  fi
}

# install_firewall <fritzbox-ip>: accept SIP/RTP of baresip from the FritzBox only.
# Direct calls from the LAN (even with a spoofed sender) then never reach baresip.
install_firewall() {
  local fritz="$1" dst="$PREFIX/firewall.nft" rtp tmp changed=0
  if ! [[ "$fritz" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
    warn "sip.yaml 'fritzbox: $fritz' is not an IPv4 address - no SIP packet filter, direct calls from the LAN reach baresip"
    systemctl disable --now doorstation-firewall >/dev/null 2>&1 || true
    return 0
  fi
  rtp="$(sed -nE 's/^rtp_ports[[:space:]]+([0-9]+-[0-9]+)[[:space:]]*$/\1/p' "$VAR/baresip/config")"
  [ -n "$rtp" ] || die "rtp_ports missing in $VAR/baresip/config"
  tmp="$(tmpfile)"
  sed -e "s|@FRITZBOX@|$fritz|" -e "s|@RTP_PORTS@|$rtp|" "$SRC/deploy/nftables/doorstation.nft.template" > "$tmp"
  nft -c -f "$tmp" || { rm -f "$tmp"; die "invalid packet filter"; }
  copy_if_changed "$tmp" "$dst" && changed=1
  rm -f "$tmp"
  install_unit doorstation-firewall && changed=1
  systemctl enable --quiet doorstation-firewall
  if [ "$changed" -eq 1 ] || ! systemctl is-active --quiet doorstation-firewall; then
    log "(Re)loading packet filter doorstation-firewall"; systemctl restart doorstation-firewall
  fi
}

# install_timesync <server>: use the FritzBox as time server. The Pi has no real-time clock; after a
# power failure the FritzBox answers at once in the LAN, the internet pool stays as fallback.
install_timesync() {
  local server="$1" tmp
  if [ -z "$server" ]; then
    # time_server: null - keep the system default
    if [ -f "$TIMESYNC_DIR/doorstation.conf" ]; then
      rm -f "$TIMESYNC_DIR/doorstation.conf"
      log "Time server: system default"
      systemctl restart systemd-timesyncd
    fi
    return 0
  fi
  if ! [[ "$server" =~ ^[A-Za-z0-9.:-]+$ ]]; then
    warn "time server '$server' invalid - keeping the default time servers"
    return 0
  fi
  install -d -m 755 "$TIMESYNC_DIR"
  tmp="$(tmpfile)"
  printf '%s\n' "# Generated by install.sh from /etc/doorstation/sip.yaml (fritzbox)" "[Time]" "NTP=$server" \
    "FallbackNTP=0.debian.pool.ntp.org 1.debian.pool.ntp.org 2.debian.pool.ntp.org 3.debian.pool.ntp.org" > "$tmp"
  if copy_if_changed "$tmp" "$TIMESYNC_DIR/doorstation.conf"; then
    log "Time server: $server (fallback: Debian pool)"
    systemctl restart systemd-timesyncd
  fi
  rm -f "$tmp"
}

# time_server_from_config <sip.yaml> <fritzbox>: the time server to use; empty = system default.
# Without "time_server" the FritzBox is used; "time_server: null" keeps the system default.
time_server_from_config() {
  local cfg="$1" fritz="$2" server
  if ! grep -qE '^time_server:' "$cfg"; then
    echo "$fritz"
    return 0
  fi
  server="$(yaml_value "$cfg" time_server)"
  case "$server" in null|Null|NULL|"~") server="" ;; esac
  echo "$server"
}

install_sip() {
  local restart_sip=0 restart_baresip=0
  local pw="$ETC/secrets/sip_password"
  if [ ! -s "$pw" ]; then
    # Fresh installation: the password comes later - set up the rest anyway.
    warn "SIP password missing ($pw) - SIP skipped. See docs/installation.md, section 4, then run install.sh again"
    return 0
  fi
  if head -n1 "$pw" | tr -d '\r' | grep -q '[;>"[:space:]]'; then
    # Would break the baresip accounts line; registration would fail silently.
    warn "SIP password contains a character that is not allowed (; > \" or space) - SIP skipped. Set a different password in the FritzBox"
    return 0
  fi
  [ "$AUDIO_RESTARTED" -eq 0 ] || restart_baresip=1
  install_python_package sip "$SRC/services/sip" && { restart_sip=1; restart_baresip=1; }
  install_config sip
  install_config audio
  install -d -m 700 -o "$SVC_USER" -g "$SVC_USER" "$VAR/sip" "$VAR/baresip"

  local fritz user tmp
  fritz="$(yaml_value "$ETC/sip.yaml" fritzbox)"; user="$(yaml_value "$ETC/sip.yaml" username)"
  [ -n "$fritz" ] && [ -n "$user" ] || die "sip.yaml: fritzbox or username missing"

  copy_if_changed "$SRC/services/sip/baresip/config.template" "$VAR/baresip/config" 600 && restart_baresip=1
  tmp="$(tmpfile)"
  sed -e "s|@USERNAME@|$user|" -e "s|@FRITZBOX@|$fritz|" "$SRC/services/sip/baresip/accounts.template" \
    | PW="$(head -n1 "$pw" | tr -d '\r')" awk '{ i = index($0, "@PASSWORD@"); if (i) $0 = substr($0, 1, i - 1) ENVIRON["PW"] substr($0, i + 10); print }' > "$tmp"
  copy_if_changed "$tmp" "$VAR/baresip/accounts" 600 && restart_baresip=1
  rm -f "$tmp"
  chown -R "$SVC_USER:$SVC_USER" "$VAR/baresip"
  install_firewall "$fritz"
  install_timesync "$(time_server_from_config "$ETC/sip.yaml" "$fritz")"

  local uid; uid="$(id -u "$SVC_USER")"
  tmp="$(tmpfile)"
  sed "s|@UID@|$uid|g" "$SRC/deploy/systemd/doorstation-baresip.service.template" > "$tmp"
  if copy_if_changed "$tmp" /etc/systemd/system/doorstation-baresip.service; then
    systemctl daemon-reload; restart_baresip=1
  fi
  rm -f "$tmp"
  install_unit doorstation-sip && restart_sip=1
  # Restart baresip on request of the SIP adapter (it stops answering after a clock jump).
  install_unit doorstation-baresip-restart || true
  local path_unit=/etc/systemd/system/doorstation-baresip-restart.path path_changed=0
  copy_if_changed "$SRC/deploy/systemd/doorstation-baresip-restart.path" "$path_unit" && path_changed=1
  [ "$path_changed" -eq 0 ] || systemctl daemon-reload
  systemctl enable --quiet doorstation-baresip-restart.path
  if [ "$path_changed" -eq 1 ] || ! systemctl is-active --quiet doorstation-baresip-restart.path; then
    systemctl restart doorstation-baresip-restart.path
  fi
  systemctl enable --quiet doorstation-baresip doorstation-sip
  if [ "$restart_baresip" -eq 1 ] || ! systemctl is-active --quiet doorstation-baresip; then
    log "(Re)starting doorstation-baresip"; systemctl restart doorstation-baresip
  fi
  if [ "$restart_sip" -eq 1 ] || ! systemctl is-active --quiet doorstation-sip; then
    log "(Re)starting doorstation-sip"; systemctl restart doorstation-sip
  fi
}

install_rfid() {
  local restart=0
  install_python_package rfid "$SRC/services/rfid" && restart=1
  install_config rfid
  install -d -m 700 -o "$SVC_USER" -g "$SVC_USER" "$VAR/rfid"

  # UART for the PN532: enable it, Bluetooth off, serial console off.
  local cfgtxt="$BOOT/config.txt" cmdline="$BOOT/cmdline.txt"
  if [ -f "$cfgtxt" ]; then
    config_txt_add "$cfgtxt" enable_uart=1 && REBOOT_NEEDED=1
    config_txt_add "$cfgtxt" dtoverlay=disable-bt && REBOOT_NEEDED=1
  fi
  if [ -f "$cmdline" ] && grep -q 'console=serial0' "$cmdline"; then
    if command -v raspi-config >/dev/null; then
      raspi-config nonint do_serial_cons 1
    else
      sed -i 's/console=serial0,[0-9]* //' "$cmdline"
    fi
    REBOOT_NEEDED=1
  fi
  if systemctl list-unit-files hciuart.service >/dev/null 2>&1; then
    systemctl disable --now hciuart >/dev/null 2>&1 || true
  fi

  install_unit doorstation-rfid && restart=1
  systemctl enable --quiet doorstation-rfid
  if [ "$restart" -eq 1 ] || ! systemctl is-active --quiet doorstation-rfid; then
    log "(Re)starting doorstation-rfid"; systemctl restart doorstation-rfid
  fi
}

# rfid-import <dir>: take over hap.state and homekey.json of an existing pairing.
do_rfid_import() {
  local from="${1:?directory with hap.state and homekey.json missing}" f
  for f in hap.state homekey.json; do
    [ -s "$from/$f" ] || die "$from/$f missing"
  done
  # Never overwrite an existing pairing. A hap.state without homekey.json comes from an
  # unpaired first start (the service creates it right away) and is moved aside.
  [ -e "$VAR/rfid/homekey.json" ] && die "$VAR/rfid/homekey.json already exists - there is a pairing already, nothing taken over"
  install -d -m 700 -o "$SVC_USER" -g "$SVC_USER" "$VAR/rfid"
  systemctl stop doorstation-rfid 2>/dev/null || true
  [ -e "$VAR/rfid/hap.state" ] && mv "$VAR/rfid/hap.state" "$VAR/rfid/hap.state.bak"
  for f in hap.state homekey.json; do
    install -m 600 -o "$SVC_USER" -g "$SVC_USER" "$from/$f" "$VAR/rfid/$f"
  done
  systemctl start doorstation-rfid 2>/dev/null || true
  log "Pairing taken over from $from"
}

install_sound() {
  local restart=0 tmp uid
  install_python_package sound "$SRC/services/sound" && restart=1
  [ "$AUDIO_RESTARTED" -eq 0 ] || restart=1
  install_config sound
  install -d -m 755 -o "$SVC_USER" -g "$SVC_USER" "$VAR/sounds"
  if [ ! -e "$VAR/sounds/beep.wav" ]; then
    install -m 644 -o "$SVC_USER" -g "$SVC_USER" "$SRC/services/sound/sounds/beep.wav" "$VAR/sounds/beep.wav"
  fi
  uid="$(id -u "$SVC_USER")"
  tmp="$(tmpfile)"
  sed "s|@UID@|$uid|g" "$SRC/deploy/systemd/doorstation-sound.service.template" > "$tmp"
  if copy_if_changed "$tmp" /etc/systemd/system/doorstation-sound.service; then
    systemctl daemon-reload; restart=1
  fi
  rm -f "$tmp"
  systemctl enable --quiet doorstation-sound
  if [ "$restart" -eq 1 ] || ! systemctl is-active --quiet doorstation-sound; then
    log "(Re)starting doorstation-sound"; systemctl restart doorstation-sound
  fi
}

do_audio_info() {
  cat /proc/asound/cards
  local n
  for n in $(sed -nE 's/^ *([0-9]+) \[.*USB.*/\1/p' /proc/asound/cards); do
    echo "--- Controls of card $n:"
    amixer -c "$n" scontrols
  done
}

do_install() {
  install_base
  install_mosquitto
  install_bridge
  install_gpio
  install_audio
  install_sip
  install_sound
  install_rfid
  log "Done"
  local w
  for w in "${WARNINGS[@]}"; do echo "WARNING: $w" >&2; done
  if [ "$REBOOT_NEEDED" -eq 1 ]; then
    echo "==> Boot settings (config.txt/cmdline.txt) changed: please reboot (sudo reboot)"
  fi
}

do_backup() {
  local out="${1:?target file missing}"
  # Contains secrets (passwords, HomeKit keys): readable by root only.
  (umask 077; tar czf "$out" -C / "${ETC#/}" "${VAR#/}")
  chmod 600 "$out"
  log "Backup written: $out"
}

do_restore() {
  local in="${1:?source file missing}"
  local units
  units="$(systemctl list-units --plain --no-legend 'doorstation-*' | awk '{print $1}')"
  [ -n "$units" ] && systemctl stop $units
  tar xzf "$in" -C /
  chown -R "$SVC_USER:$SVC_USER" "$VAR"
  chown -R root:root "$ETC/secrets"
  chmod 700 "$ETC/secrets"
  [ -n "$units" ] && systemctl start $units
  log "Restored from $in - now run 'sudo ./install.sh' (bridge, baresip account, packet filter)"
}

main() {
  require_root "$@"
  RUN_TMP="$(mktemp -d)"
  trap 'rm -rf "$RUN_TMP"' EXIT
  case "${1:-install}" in
    install) do_install ;;
    backup) do_backup "${2:-}" ;;
    restore) do_restore "${2:-}" ;;
    audio-info) do_audio_info ;;
    rfid-import) do_rfid_import "${2:-}" ;;
    *) echo "Unknown command: $1" >&2; exit 2 ;;
  esac
}

# Run only when called directly; when sourced, the functions are available for tests.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
