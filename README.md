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

Die Einrichtung läuft über die Oberfläche, mit Suche nach Kameras im Heimnetz, neuer Anmeldung (Reauth), Verbindung ändern (Reconfigure) und Diagnose-Download.

### Kameras finden

Die Integration fragt alle Adressen in deinem Heimnetz (das /24-Netz von Home Assistant) ab und erkennt jede Kamera daran, dass ihre Weboberfläche nach der Kamera-Anmeldung verlangt. Die Suche hängt nicht an der MAC-Adresse, die bei Kameras dieser Bauart nicht einheitlich beginnt. Sie läuft nach dem Start von Home Assistant, danach jede Stunde und jedes Mal, wenn du **Gerät hinzufügen** öffnest.

- **Entdeckt:** Jede gefundene Kamera erscheint unter **Einstellungen → Geräte & Dienste** im Bereich **Entdeckt**, mit **Hinzufügen** daneben. Eine Kamera, die schon eingerichtet ist, bekommt keinen Kasten, ihre Adresse wird aber nachgezogen, falls sie sich geändert hat.
- **Gerät hinzufügen:** Der Dialog listet die Kameras, die noch nicht eingerichtet sind, mit ihrer IP-Adresse zur Auswahl. Eine Adresse kannst du auch von Hand eintragen.

Für die Kästen liest die Integration die MAC-Adresse aus der ARP-Tabelle von Home Assistant (`/proc/net/arp`). Ist die nicht lesbar, etwa weil Home Assistant in einem Docker-Netz ohne Zugriff aufs Heimnetz läuft, bleiben die Kästen aus und nur die Auswahlliste im Dialog funktioniert. Zusätzlich schlägt Home Assistant Kameras vor, die per DHCP mit dem MAC-Anfang `00:0F:97` auffallen. Kameras in einem anderen Netz, etwa einem Gäste-VLAN, findest du nur über die Eingabe von Hand.

### Bewegung und Personen

Die Kamera meldet Bewegung per ONVIF. Home Assistant gibt dafür einen Webhook an und die Kamera schickt ihre Meldungen per HTTP dorthin. Dafür muss die Kamera Home Assistant erreichen können, und Home Assistant braucht eine **kurze interne URL mit HTTP** (Einstellungen → System → Netzwerk), am besten die IP-Adresse wie `http://192.168.178.53:8123`. Die Kamera verträgt nur kurze Adressen: Die interne URL darf höchstens 35 Zeichen lang sein, sonst bleiben die Bewegungsmeldungen aus und im Log steht eine Warnung.

Der Sensor `Bewegung` zeigt die **normale Bewegungserkennung** der Kamera. Die KI-Erkennung ändert daran nichts: Die Kamera meldet auch bei eingeschalteter KI keine Personen getrennt von anderer Bewegung, in Tests kam bei Schwenken und bei einem Menschen vor der Kamera immer dieselbe Meldung. Die KI-Erkennung wirkt in der Kamera selbst (Rahmen im Bild, Auto-Tracking, Aufnahmen auf der SD-Karte). Alle ONVIF-Meldungen erscheinen außerdem als Ereignis `ctronics_cam_event` mit Thema und Daten, falls du eigene Auslöser bauen möchtest.

### Präfix für den Namen

Beim Hinzufügen einer Kamera ist das Feld **Präfix** ein Pflichtfeld. Es wird dem Namen der Kamera vorangestellt: Aus dem Präfix `Spielzimmer` und dem Namen `Fuchsrevier` wird das Gerät **Spielzimmer Fuchsrevier**, und die Entity-IDs beginnen mit `spielzimmer_fuchsrevier` (zum Beispiel `camera.spielzimmer_fuchsrevier`). So bleiben die IDs eindeutig, auch wenn gleiche Namen schon von einer anderen Integration belegt sind.

Das Präfix lässt sich später unter **Konfigurieren** ändern, es bleibt dort ein Pflichtfeld und darf nicht leer sein. Das ändert den Gerätenamen, aber nicht die Entity-IDs: Die behalten das Präfix, mit dem sie angelegt wurden. Hast du das Gerät in Home Assistant von Hand umbenannt, zeigt Home Assistant weiter deinen Namen. Beim Speichern lädt Home Assistant die Kamera kurz neu. Kameras, die vor der Pflicht ohne Präfix eingerichtet wurden, brauchen beim nächsten Speichern der Optionen eins.

### Preset-Positionen

Die Positionen selbst liegen in der Kamera (1 bis 64). Die Kamera kennt keine Namen, deshalb trägst du sie unter **Einstellungen → Geräte & Dienste → Ctronics 4K Cam → Konfigurieren** ein, eine Position pro Zeile:

```
1: Schaukel
10: Bett
```

Danach erscheint das Auswahlfeld `Preset-Position`. Speichern und Löschen läuft über die Dienste `ptz_save_preset` und `ptz_delete_preset`, damit nichts aus Versehen überschrieben wird.

## Fehlersuche

- **Sensor „Bewegung“ ist nicht verfügbar.** Die Kamera meldet Bewegung nur, solange ihr ONVIF-Dienst läuft. Dieser Dienst kann bei den Kameras von selbst wegbrechen, Stream, Schnappschuss und Steuerung laufen dann weiter. Die Integration versucht es mit wachsenden Pausen neu und zeigt nach einigen Minuten unter **Einstellungen → System → Reparaturen** einen Hinweis. Meist hilft es, die Kamera kurz vom Strom zu trennen. Ein Ausschalten und Einschalten von ONVIF in den Kameraeinstellungen reicht nicht.
- **Im Log steht, die Adresse sei zu lang.** Die interne URL von Home Assistant darf höchstens 35 Zeichen haben, siehe oben.
- **Entity-IDs enden auf `_2`.** Das passiert, wenn dieselben Namen schon von einer anderen Integration belegt sind. Neue Kameras bekommen deshalb beim Hinzufügen ein Pflicht-Präfix (siehe oben). Bei einer schon eingerichteten Kamera änderst du die IDs in den Entity-Einstellungen.

## Installation (HACS)

1. HACS öffnen, oben rechts **Benutzerdefinierte Repositories** wählen.
2. `https://github.com/RedDragonNode/ha-ctronics-cam` als Typ **Integration** hinzufügen.
3. **Ctronics 4K Cam** herunterladen und Home Assistant neu starten.
4. Unter **Einstellungen → Geräte & Dienste** die Integration hinzufügen. Die Kameras im Heimnetz stehen dann zur Auswahl.

Du brauchst IP-Adresse, Benutzername und Passwort der Kamera, dieselben wie in der Ctronics-Pro-App. Reserviere die IP-Adresse im Router.

---

# Ctronics 4K Cam for Home Assistant (English)

Local integration for **Ctronics 4K pan/tilt cameras** running Hipcam firmware (Hi3510 CGI, RTSP, ONVIF), for example the indoor camera with auto tracking and AI detection. Everything runs on your LAN, no cloud and no account needed. Protocol notes: [docs/protocol.md](docs/protocol.md).

**Features:** RTSP live stream and snapshot, PTZ buttons, a selector for named presets, switches for AI detection and auto tracking, detection type and threshold, night vision LEDs, flip and mirror, a motion `binary_sensor` via ONVIF events (general motion, the camera does not report persons separately), SD card diagnostics, four PTZ services, a network scan that shows every camera on your home network under *Discovered* and in the add dialog, DHCP discovery, reauth, reconfigure and diagnostics.

**Name prefix:** when adding a camera the *Prefix* field is required. It puts a word in front of the camera name, so "Playroom" and "Fox den" become the device "Playroom Fox den" with entity IDs starting with `playroom_fox_den`. It can be changed later under *Configure* (still required); that renames the device but leaves the entity IDs alone. Cameras set up without one keep working until you save their options, which then asks for one.

**Motion events** are pushed by the camera to a Home Assistant webhook, so Home Assistant needs an internal URL using plain HTTP that the camera can reach.

**Install:** HACS → Custom repositories → add `https://github.com/RedDragonNode/ha-ctronics-cam` as *Integration* → download → restart Home Assistant → Settings → Devices & services → add *Ctronics 4K Cam*.

## Lizenz / License

[MIT](LICENSE)
