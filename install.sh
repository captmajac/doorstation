#!/usr/bin/env bash
# Einrichtung der Türstation auf Raspberry Pi OS (Debian 13 Trixie).
# Aufruf (als root):
#   ./install.sh               Installation bzw. Aktualisierung (beliebig oft wiederholbar)
#   ./install.sh backup  <datei.tar.gz>
#   ./install.sh restore <datei.tar.gz>
#   ./install.sh audio-info    Soundkarten und Reglernamen anzeigen
#   ./install.sh rfid-import <ordner>   bestehende Home-Key-Paarung übernehmen
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
PREFIX=/opt/doorstation
SRC="$PREFIX/src"
ETC="${DOORSTATION_ETC:-/etc/doorstation}"       # Testumgebung: DOORSTATION_ETC
VAR="${DOORSTATION_VAR:-/var/lib/doorstation}"  # Testumgebung: DOORSTATION_VAR
BOOT="${DOORSTATION_BOOT:-/boot/firmware}"
SVC_USER=doorstation
RUN_TMP=""          # eigener Temp-Ordner je Lauf, wird beim Beenden gelöscht (Passwörter!)
WARNINGS=()
AUDIO_RESTARTED=0   # PipeWire neu gestartet → baresip und sound brauchen neue Audioknoten

log() { echo "==> $*"; }

# Warnung sofort ausgeben und am Ende noch einmal zusammenfassen.
warn() { echo "WARNUNG: $*" >&2; WARNINGS+=("$*"); }

tmpfile() { mktemp -p "${RUN_TMP:-${TMPDIR:-/tmp}}"; }

# Abbruch mit Meldung. Nötig, weil Funktionen in "&&"-Ketten nicht unter set -e laufen.
die() { echo "FEHLER: $*" >&2; exit 1; }

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "Bitte als root ausführen: sudo $0 $*" >&2
    exit 1
  fi
}

# Kopiert $1 nach $2, wenn sich der Inhalt unterscheidet. Exit 0 = geändert, 1 = unverändert.
copy_if_changed() {
  local src="$1" dst="$2" mode="${3:-644}"
  if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
    return 1
  fi
  install -m "$mode" "$src" "$dst" || die "kann $dst nicht schreiben"
  return 0
}

install_base() {
  log "Pakete"
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
    mosquitto mosquitto-clients nftables python3-venv python3-libgpiod rsync >/dev/null

  log "Benutzer $SVC_USER"
  if ! id "$SVC_USER" >/dev/null 2>&1; then
    useradd --system --home "$VAR" --shell /usr/sbin/nologin "$SVC_USER"
  fi
  usermod -a -G gpio,dialout,audio "$SVC_USER"

  log "Verzeichnisse"
  install -d -m 755 "$ETC" "$PREFIX" "$PREFIX/venv"
  # Geheimnisse liest nur install.sh (root); kein Dienst braucht sie zur Laufzeit.
  install -d -m 700 -o root -g root "$ETC/secrets"
  find "$ETC/secrets" -type f -exec chown root:root {} + -exec chmod 600 {} +
  install -d -m 755 -o "$SVC_USER" -g "$SVC_USER" "$VAR" "$VAR/sounds"

  log "Quellcode nach $SRC"
  rsync -a --delete --exclude .git --exclude .venv --exclude .superpowers \
    --exclude __pycache__ --exclude '*.egg-info' "$REPO/" "$SRC/"
}

install_mosquitto() {
  log "Mosquitto (lokal)"
  local changed=0
  copy_if_changed "$SRC/deploy/mosquitto/doorstation.conf" /etc/mosquitto/conf.d/doorstation.conf && changed=1
  systemctl enable --quiet mosquitto
  if [ "$changed" -eq 1 ] || ! systemctl is-active --quiet mosquitto; then
    systemctl restart mosquitto
  fi
}

# install_python_package <name> <pfad> [--system-site-packages]
# Legt $PREFIX/venv/<name> an und installiert common und <pfad> hinein.
# Exit 0 = Code geändert (Dienst neu starten), 1 = unverändert.
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
  log "Python-Paket $name"
  if [ ! -x "$venv/bin/python" ]; then
    # shellcheck disable=SC2086
    python3 -m venv $opt "$venv" || die "venv $venv konnte nicht angelegt werden"
  fi
  "$venv/bin/pip" install -q --disable-pip-version-check --upgrade "$SRC/common" "$path" \
    || die "pip-Installation von $name fehlgeschlagen"
  echo "$hash" > "$stamp"
  return 0
}

# install_config <dienst>: Beispielkonfiguration nur kopieren, wenn noch keine existiert.
install_config() {
  local svc="$1"
  if [ ! -f "$ETC/$svc.yaml" ]; then
    log "Beispielkonfiguration $ETC/$svc.yaml"
    install -m 644 "$SRC/config-examples/$svc.yaml" "$ETC/$svc.yaml"
  fi
}

# Liest einen Wert aus einer flachen YAML-Datei (schlüssel: wert).
yaml_value() {
  sed -nE "s/^$2:[[:space:]]*\"?([^\"#]*[^\"#[:space:]])\"?[[:space:]]*(#.*)?$/\1/p" "$1" | head -n1
}

# config_txt_add <datei> <zeile>: Zeile im Abschnitt [all] sicherstellen, damit sie für jedes
# Pi-Modell gilt (am Dateiende steht sonst evtl. [pi5] o. Ä.). Exit 0 = ergänzt, 1 = vorhanden.
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

# render_bridge <bridge.yaml> <passwortdatei> <ziel>: Bridge-Konfiguration erzeugen.
# Werte werden geprüft statt escaped – ein Sonderzeichen würde sonst die Mosquitto-Konfiguration zerlegen.
render_bridge() {
  local cfg="$1" pwfile="$2" out="$3" host port user prefix pass
  host="$(yaml_value "$cfg" host)"; port="$(yaml_value "$cfg" port)"
  user="$(yaml_value "$cfg" username)"; prefix="$(yaml_value "$cfg" prefix)"
  prefix="${prefix:-doorstation}"
  [[ "$host" =~ ^[A-Za-z0-9.:-]+$ ]] || { echo "bridge.yaml: host '$host' ungültig" >&2; return 1; }
  [[ "$port" =~ ^[0-9]{1,5}$ ]] || { echo "bridge.yaml: port '$port' ungültig" >&2; return 1; }
  [[ "$user" =~ ^[A-Za-z0-9._@-]+$ ]] || { echo "bridge.yaml: username '$user' ungültig" >&2; return 1; }
  [[ "$prefix" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "bridge.yaml: prefix '$prefix' ungültig (ohne / + #)" >&2; return 1; }
  pass="$(head -n1 "$pwfile" | tr -d '\r')"
  [ -n "$pass" ] || { echo "bridge_password ist leer" >&2; return 1; }
  sed -e "s|@HOST@|$host|" -e "s|@PORT@|$port|" -e "s|@USERNAME@|$user|" \
      -e "s|@PREFIX@|$prefix|g" "$SRC/deploy/mosquitto/bridge.conf.template" \
    | PW="$pass" awk '{ i = index($0, "@PASSWORD@"); if (i) $0 = substr($0, 1, i - 1) ENVIRON["PW"] substr($0, i + 10); print }' > "$out"
}

# apply_mosquitto_conf <neu> <ziel>: Konfiguration übernehmen und Mosquitto neu starten. Startet er
# damit nicht, wird die vorherige wiederhergestellt – ohne Broker klingelt nichts.
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
  warn "Mosquitto startet mit der neuen Bridge-Konfiguration nicht – vorherige wiederhergestellt (journalctl -u mosquitto)"
  if [ -n "$backup" ]; then
    install -m 640 "$backup" "$dst"; chown root:mosquitto "$dst"
  else
    rm -f "$dst"
  fi
  systemctl restart mosquitto || warn "Mosquitto startet auch mit der vorherigen Konfiguration nicht"
  return 0
}

install_bridge() {
  local cfg="$ETC/bridge.yaml" pw="$ETC/secrets/bridge_password"
  local dst=/etc/mosquitto/conf.d/doorstation-bridge.conf tmp
  if [ ! -f "$cfg" ] || [ ! -s "$pw" ]; then
    if [ -f "$dst" ]; then
      log "Bridge entfernt (keine Konfiguration)"
      rm -f "$dst"
      systemctl restart mosquitto
    else
      log "Bridge: keine Konfiguration ($cfg, $pw) – übersprungen"
    fi
    return 0
  fi
  log "Bridge zu IP-Symcon"
  tmp="$(tmpfile)"
  if ! render_bridge "$cfg" "$pw" "$tmp"; then
    warn "Bridge nicht geändert – $cfg bzw. Passwort prüfen"
  else
    apply_mosquitto_conf "$tmp" "$dst"
  fi
  rm -f "$tmp"
}

# install_unit <name>: systemd-Unit installieren. Exit 0 = geändert.
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
    log "Dienst doorstation-gpio (neu) starten"
    systemctl restart doorstation-gpio
  fi
}

REBOOT_NEEDED=0

# Systemd-Benutzerbefehl für den Dienstbenutzer (dessen User-Manager läuft dank Linger).
user_systemctl() {
  local uid; uid="$(id -u "$SVC_USER")"
  runuser -u "$SVC_USER" -- env XDG_RUNTIME_DIR="/run/user/$uid" systemctl --user "$@"
}

install_audio() {
  log "Audio (PipeWire mit Echounterdrückung)"
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
    pipewire pipewire-alsa pipewire-bin wireplumber alsa-utils baresip-core >/dev/null \
    || die "Audio-Pakete konnten nicht installiert werden"
  loginctl enable-linger "$SVC_USER"
  local uid; uid="$(id -u "$SVC_USER")"
  local i; for i in $(seq 1 20); do [ -S "/run/user/$uid/bus" ] && break; sleep 0.5; done
  [ -S "/run/user/$uid/bus" ] || die "User-Manager von $SVC_USER läuft nicht"
  local confdir="$VAR/.config/pipewire/pipewire.conf.d" changed=0
  install -d -o "$SVC_USER" -g "$SVC_USER" "$VAR/.config" "$VAR/.config/pipewire" "$confdir"
  copy_if_changed "$SRC/deploy/pipewire/60-echo-cancel.conf" "$confdir/60-echo-cancel.conf" && changed=1
  chown "$SVC_USER:$SVC_USER" "$confdir/60-echo-cancel.conf"
  user_systemctl enable --quiet pipewire.socket pipewire wireplumber
  if [ "$changed" -eq 1 ]; then
    user_systemctl restart pipewire wireplumber
    AUDIO_RESTARTED=1
  else
    user_systemctl start pipewire wireplumber
  fi

  # Onboard-Audio (Klinke, HDMI) abschalten: dann ist der USB-Stick das einzige Audiogerät.
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

# install_firewall <fritzbox-ip>: SIP/RTP von baresip nur von der FritzBox annehmen.
# Direkte Anrufe aus dem LAN (auch mit gefälschtem Absender) erreichen baresip dann nicht.
install_firewall() {
  local fritz="$1" dst="$PREFIX/firewall.nft" rtp tmp changed=0
  if ! [[ "$fritz" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
    warn "sip.yaml 'fritzbox: $fritz' ist keine IPv4-Adresse – kein SIP-Paketfilter, direkte Anrufe aus dem LAN erreichen baresip"
    systemctl disable --now doorstation-firewall >/dev/null 2>&1 || true
    return 0
  fi
  rtp="$(sed -nE 's/^rtp_ports[[:space:]]+([0-9]+-[0-9]+)[[:space:]]*$/\1/p' "$VAR/baresip/config")"
  [ -n "$rtp" ] || die "rtp_ports fehlt in $VAR/baresip/config"
  tmp="$(tmpfile)"
  sed -e "s|@FRITZBOX@|$fritz|" -e "s|@RTP_PORTS@|$rtp|" "$SRC/deploy/nftables/doorstation.nft.template" > "$tmp"
  nft -c -f "$tmp" || { rm -f "$tmp"; die "Paketfilter ungültig"; }
  copy_if_changed "$tmp" "$dst" && changed=1
  rm -f "$tmp"
  install_unit doorstation-firewall && changed=1
  systemctl enable --quiet doorstation-firewall
  if [ "$changed" -eq 1 ] || ! systemctl is-active --quiet doorstation-firewall; then
    log "Paketfilter doorstation-firewall (neu) laden"; systemctl restart doorstation-firewall
  fi
}

install_sip() {
  local restart_sip=0 restart_baresip=0
  local pw="$ETC/secrets/sip_password"
  if [ ! -s "$pw" ]; then
    # Frische Installation: Passwort kommt erst danach – den Rest trotzdem einrichten.
    warn "SIP-Passwort fehlt ($pw) – SIP übersprungen. Ablegen siehe docs/installation.md, Abschnitt 4, dann install.sh erneut"
    return 0
  fi
  if head -n1 "$pw" | tr -d '\r' | grep -q '[;>"[:space:]]'; then
    # Würde die baresip-accounts-Zeile zerlegen; die Anmeldung schlüge still fehl.
    warn "SIP-Passwort enthält ein nicht erlaubtes Zeichen (; > \" oder Leerzeichen) – SIP übersprungen. In der FritzBox ein anderes Passwort vergeben"
    return 0
  fi
  [ "$AUDIO_RESTARTED" -eq 0 ] || restart_baresip=1
  install_python_package sip "$SRC/services/sip" && { restart_sip=1; restart_baresip=1; }
  install_config sip
  install_config audio
  install -d -m 700 -o "$SVC_USER" -g "$SVC_USER" "$VAR/sip" "$VAR/baresip"

  local fritz user tmp
  fritz="$(yaml_value "$ETC/sip.yaml" fritzbox)"; user="$(yaml_value "$ETC/sip.yaml" username)"
  [ -n "$fritz" ] && [ -n "$user" ] || die "sip.yaml: fritzbox oder username fehlt"

  copy_if_changed "$SRC/services/sip/baresip/config.template" "$VAR/baresip/config" 600 && restart_baresip=1
  tmp="$(tmpfile)"
  sed -e "s|@USERNAME@|$user|" -e "s|@FRITZBOX@|$fritz|" "$SRC/services/sip/baresip/accounts.template" \
    | PW="$(head -n1 "$pw" | tr -d '\r')" awk '{ i = index($0, "@PASSWORD@"); if (i) $0 = substr($0, 1, i - 1) ENVIRON["PW"] substr($0, i + 10); print }' > "$tmp"
  copy_if_changed "$tmp" "$VAR/baresip/accounts" 600 && restart_baresip=1
  rm -f "$tmp"
  chown -R "$SVC_USER:$SVC_USER" "$VAR/baresip"
  install_firewall "$fritz"

  local uid; uid="$(id -u "$SVC_USER")"
  tmp="$(tmpfile)"
  sed "s|@UID@|$uid|g" "$SRC/deploy/systemd/doorstation-baresip.service.template" > "$tmp"
  if copy_if_changed "$tmp" /etc/systemd/system/doorstation-baresip.service; then
    systemctl daemon-reload; restart_baresip=1
  fi
  rm -f "$tmp"
  install_unit doorstation-sip && restart_sip=1
  systemctl enable --quiet doorstation-baresip doorstation-sip
  if [ "$restart_baresip" -eq 1 ] || ! systemctl is-active --quiet doorstation-baresip; then
    log "Dienst doorstation-baresip (neu) starten"; systemctl restart doorstation-baresip
  fi
  if [ "$restart_sip" -eq 1 ] || ! systemctl is-active --quiet doorstation-sip; then
    log "Dienst doorstation-sip (neu) starten"; systemctl restart doorstation-sip
  fi
}

install_rfid() {
  local restart=0
  install_python_package rfid "$SRC/services/rfid" && restart=1
  install_config rfid
  install -d -m 700 -o "$SVC_USER" -g "$SVC_USER" "$VAR/rfid"

  # UART für den PN532: freischalten, Bluetooth ab, serielle Konsole ab.
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
    log "Dienst doorstation-rfid (neu) starten"; systemctl restart doorstation-rfid
  fi
}

# rfid-import <ordner>: hap.state und homekey.json einer bestehenden Paarung übernehmen.
do_rfid_import() {
  local from="${1:?Ordner mit hap.state und homekey.json fehlt}" f
  for f in hap.state homekey.json; do
    [ -s "$from/$f" ] || die "$from/$f fehlt"
  done
  # Eine bestehende Paarung nie überschreiben. Ein hap.state ohne homekey.json stammt von einem
  # ungepaarten ersten Start (der Dienst legt es sofort an) und wird beiseitegelegt.
  [ -e "$VAR/rfid/homekey.json" ] && die "$VAR/rfid/homekey.json existiert schon – es gibt bereits eine Paarung, nichts übernommen"
  install -d -m 700 -o "$SVC_USER" -g "$SVC_USER" "$VAR/rfid"
  systemctl stop doorstation-rfid 2>/dev/null || true
  [ -e "$VAR/rfid/hap.state" ] && mv "$VAR/rfid/hap.state" "$VAR/rfid/hap.state.bak"
  for f in hap.state homekey.json; do
    install -m 600 -o "$SVC_USER" -g "$SVC_USER" "$from/$f" "$VAR/rfid/$f"
  done
  systemctl start doorstation-rfid 2>/dev/null || true
  log "Paarung aus $from übernommen"
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
    log "Dienst doorstation-sound (neu) starten"; systemctl restart doorstation-sound
  fi
}

do_audio_info() {
  cat /proc/asound/cards
  local n
  for n in $(sed -nE 's/^ *([0-9]+) \[.*USB.*/\1/p' /proc/asound/cards); do
    echo "--- Regler der Karte $n:"
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
  log "Fertig"
  local w
  for w in "${WARNINGS[@]}"; do echo "WARNUNG: $w" >&2; done
  if [ "$REBOOT_NEEDED" -eq 1 ]; then
    echo "==> Boot-Einstellungen (config.txt/cmdline.txt) geändert: bitte neu starten (sudo reboot)"
  fi
}

do_backup() {
  local out="${1:?Zieldatei fehlt}"
  # Enthält Geheimnisse (Passwörter, HomeKit-Schlüssel): nur für root lesbar.
  (umask 077; tar czf "$out" -C / "${ETC#/}" "${VAR#/}")
  chmod 600 "$out"
  log "Sicherung geschrieben: $out"
}

do_restore() {
  local in="${1:?Quelldatei fehlt}"
  local units
  units="$(systemctl list-units --plain --no-legend 'doorstation-*' | awk '{print $1}')"
  [ -n "$units" ] && systemctl stop $units
  tar xzf "$in" -C /
  chown -R "$SVC_USER:$SVC_USER" "$VAR"
  chown -R root:root "$ETC/secrets"
  chmod 700 "$ETC/secrets"
  [ -n "$units" ] && systemctl start $units
  log "Wiederhergestellt aus $in – jetzt 'sudo ./install.sh' ausführen (Bridge, baresip-Konto, Paketfilter)"
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
    *) echo "Unbekannter Befehl: $1" >&2; exit 2 ;;
  esac
}

# Nur bei direktem Aufruf ausführen; eingelesen (source) stehen die Funktionen für Tests bereit.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
