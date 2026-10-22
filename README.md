<p align="center">
  <img src="docs/banner.png" alt="Ctronics 4K Cam" width="520">
</p>

# Ctronics 4K Cam für Home Assistant

Lokale Integration für **Ctronics 4K Schwenk-/Neige-Kameras** (Hipcam-Firmware mit Hi3510-CGI, RTSP und ONVIF). Alles läuft im Heimnetz, es wird keine Cloud und kein Konto benötigt.

> **Status:** in Entwicklung, noch nicht lauffähig. Diese Seite wird mit jedem Schritt erweitert.

## Geplanter Funktionsumfang

- Live-Stream (RTSP) und Schnappschuss als Kamera-Entity
- PTZ-Steuerung: Richtung, Stopp, Mitte, Presets über ein einziges Auswahlfeld
- Auto-Tracking und KI-Personenerkennung ein/aus, Empfindlichkeit einstellbar
- Person und Bewegung als `binary_sensor` für Automationen
- Nachtsicht (IR-LED), Spiegeln und Drehen des Bildes
- Einrichtung über die Oberfläche (Config-Flow), mit Reauth, Reconfigure und Diagnose-Download

## Installation (HACS)

1. HACS öffnen, oben rechts **Benutzerdefinierte Repositories** wählen.
2. `https://github.com/RedDragonNode/ha-ctronics-cam` als Typ **Integration** hinzufügen.
3. **Ctronics 4K Cam** herunterladen und Home Assistant neu starten.
4. Unter **Einstellungen → Geräte & Dienste** die Integration hinzufügen.

---

# Ctronics 4K Cam for Home Assistant (English)

Local integration for **Ctronics 4K pan/tilt cameras** (Hipcam firmware with Hi3510 CGI, RTSP and ONVIF). Everything runs on your LAN, no cloud and no account needed.

> **Status:** under development, not usable yet.

**Planned:** RTSP live stream and snapshot, PTZ with a single preset selector, auto-tracking and AI person detection switches, person and motion `binary_sensor`s, night vision (IR LED), config flow with reauth, reconfigure and diagnostics.

**Install:** HACS → Custom repositories → add `https://github.com/RedDragonNode/ha-ctronics-cam` as *Integration* → download → restart Home Assistant.

## Lizenz / License

[MIT](LICENSE)
