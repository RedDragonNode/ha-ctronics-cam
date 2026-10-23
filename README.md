<p align="center">
  <img src="docs/banner.png" alt="Ctronics 4K Cam" width="520">
</p>

# Ctronics 4K Cam für Home Assistant

[![Tests](https://github.com/RedDragonNode/ha-ctronics-cam/actions/workflows/tests.yaml/badge.svg)](https://github.com/RedDragonNode/ha-ctronics-cam/actions/workflows/tests.yaml)
[![Hassfest](https://github.com/RedDragonNode/ha-ctronics-cam/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/RedDragonNode/ha-ctronics-cam/actions/workflows/hassfest.yaml)
[![HACS](https://github.com/RedDragonNode/ha-ctronics-cam/actions/workflows/hacs.yaml/badge.svg)](https://github.com/RedDragonNode/ha-ctronics-cam/actions/workflows/hacs.yaml)

Lokale Integration für **Ctronics 4K Schwenk-/Neigekameras** mit Hipcam-Firmware (Hi3510-CGI, RTSP, ONVIF), zum Beispiel die Innenkamera mit Auto-Tracking und KI-Personenerkennung. Alles läuft im Heimnetz, es wird keine Cloud und kein Konto benötigt.

Entwickelt und geprüft mit dem Modellcode `C6F0SpZ0N0PpL2`, Firmware `V30.1.60.11.88-20260204`. Wie die Kamera angesprochen wird, steht in [docs/protocol.md](docs/protocol.md).

## Funktionen

| Bereich | Entities |
|---|---|
| Video | Live-Stream (RTSP, 4K) mit Schnappschuss, Substream (standardmäßig aus) |
| PTZ | Tasten für oben, unten, links, rechts, Mitte, Stopp, Rundgänge (aus), Auswahlfeld für benannte Preset-Positionen |
| KI | Schalter `KI-Erkennung` und `Auto-Tracking`, Auswahl `Erkennungsart`, Regler `Erkennungsschwelle`, Schalter `Erkennungsrahmen im Bild` |
| Bild | `Nachtsicht-LEDs` (automatisch, an, aus), `Bild kopfüber`, `Bild spiegeln` |
| Meldungen | `Bewegung` als `binary_sensor` (über ONVIF-Ereignisse) |
| Diagnose | SD-Karte: Status, freier Platz, Kapazität (nur wenn eine Karte steckt) |
| Dienste | `ctronics_cam.ptz_move`, `ptz_goto_preset`, `ptz_save_preset`, `ptz_delete_preset` |

Die Einrichtung läuft über die Oberfläche, mit Erkennung neuer Kameras im Netz (DHCP), neuer Anmeldung (Reauth), Verbindung ändern (Reconfigure) und Diagnose-Download.

### Bewegung und Personen

Die Kamera meldet Bewegung per ONVIF. Home Assistant gibt dafür einen Webhook an und die Kamera schickt ihre Meldungen per HTTP dorthin. Dafür muss die Kamera Home Assistant erreichen können, und Home Assistant braucht eine **kurze interne URL mit HTTP** (Einstellungen → System → Netzwerk), am besten die IP-Adresse wie `http://192.168.178.53:8123`. Die Kamera verträgt nur kurze Adressen: Die interne URL darf höchstens 35 Zeichen lang sein, sonst bleiben die Bewegungsmeldungen aus und im Log steht eine Warnung.

Ist die KI-Erkennung an, meldet die Kamera nur noch erkannte Objekte der gewählten Art (Mensch, Fahrzeug, Haustier) als Bewegung. Alle ONVIF-Meldungen erscheinen außerdem als Ereignis `ctronics_cam_event` mit Thema und Daten, falls du eigene Auslöser bauen möchtest.

### Preset-Positionen

Die Positionen selbst liegen in der Kamera (1 bis 64). Die Kamera kennt keine Namen, deshalb trägst du sie unter **Einstellungen → Geräte & Dienste → Ctronics 4K Cam → Konfigurieren** ein, eine Position pro Zeile:

```
1: Schaukel
10: Bett
```

Danach erscheint das Auswahlfeld `Preset-Position`. Speichern und Löschen läuft über die Dienste `ptz_save_preset` und `ptz_delete_preset`, damit nichts aus Versehen überschrieben wird.

## Installation (HACS)

1. HACS öffnen, oben rechts **Benutzerdefinierte Repositories** wählen.
2. `https://github.com/RedDragonNode/ha-ctronics-cam` als Typ **Integration** hinzufügen.
3. **Ctronics 4K Cam** herunterladen und Home Assistant neu starten.
4. Unter **Einstellungen → Geräte & Dienste** die Integration hinzufügen. Neue Kameras werden oft automatisch vorgeschlagen.

Du brauchst IP-Adresse, Benutzername und Passwort der Kamera, dieselben wie in der Ctronics-Pro-App. Reserviere die IP-Adresse im Router.

---

# Ctronics 4K Cam for Home Assistant (English)

Local integration for **Ctronics 4K pan/tilt cameras** running Hipcam firmware (Hi3510 CGI, RTSP, ONVIF), for example the indoor camera with auto tracking and AI person detection. Everything runs on your LAN, no cloud and no account needed. Protocol notes: [docs/protocol.md](docs/protocol.md).

**Features:** RTSP live stream and snapshot, PTZ buttons, a selector for named presets, switches for AI detection and auto tracking, detection type and threshold, night vision LEDs, flip and mirror, a motion `binary_sensor` via ONVIF events, SD card diagnostics, four PTZ services, DHCP discovery, reauth, reconfigure and diagnostics.

**Motion events** are pushed by the camera to a Home Assistant webhook, so Home Assistant needs an internal URL using plain HTTP that the camera can reach.

**Install:** HACS → Custom repositories → add `https://github.com/RedDragonNode/ha-ctronics-cam` as *Integration* → download → restart Home Assistant → Settings → Devices & services → add *Ctronics 4K Cam*.

## Lizenz / License

[MIT](LICENSE)
