# Kamera-Schnittstelle (Ctronics 4K, Hipcam-Firmware)

Ermittelt an einer Kamera mit Modellcode `C6F0SpZ0N0PpL2`, Firmware `V30.1.60.11.88-20260204`, Web-Version `V3.0.7.6`.
Alle Angaben stammen aus lesenden Abfragen und aus dem Code der Web-Oberfläche der Kamera (`/web/js/*.js`).
Stand der Prüfung steht jeweils in der letzten Spalte: **gelesen** = an der Kamera abgefragt, **abgeleitet** = nur aus der Web-Oberfläche übernommen, noch nicht gegen die Kamera getestet.

## Dienste

| Port | Dienst | Anmeldung |
|---|---|---|
| 80 | Hi3510-CGI und Web-Oberfläche | HTTP Basic, Realm `cgi-bin/hi3510/param.cgi` |
| 554 | RTSP (`Hipcam RealServer/V1.0`) | Digest, Pfade `/11` (Main, 3840x2160 H.264) und `/12` (Sub, 1280x720 H.264) |
| 8080 | ONVIF (Device, Media, PTZ, Events, Imaging, Analytics) | WS-UsernameToken (Digest), schon `GetSystemDateAndTime` verlangt Anmeldung |

Unbekannte CGI-Befehle antworten mit HTTP 404, bekannte mit falschen Parametern mit `[Error]Param error.`. So lässt sich die Existenz eines Befehls prüfen.

## CGI: Format

Abfrage: `GET /cgi-bin/hi3510/param.cgi?cmd=<befehl>` (mehrere `cmd=` hintereinander möglich), Antwort sind Zeilen `var name="wert";`.
Setzen: `GET /cgi-bin/hi3510/param.cgi?cmd=<setbefehl>&-name=wert`. Die Web-Oberfläche sendet Felder mit dem Präfix `-`.

## Lesen (gelesen)

| Befehl | Felder (Auswahl) |
|---|---|
| `getserverinfo` | `model`, `hardVersion`, `softVersion`, `webVersion`, `name`, `startdate`, `sdstatus`, `sdfreespace`, `sdtotalspace` |
| `getnetattr` | `ip`, `netmask`, `gateway`, `macaddress`, `networktype` |
| `getimageattr` | `flip`, `mirror`, `night`, `brightness`, `contrast`, `saturation`, `sharpness`, `wdr` |
| `getinfrared` | `infraredstat` (`open` / `close`) |
| `getircutattr` | `saradc_switch_value`, `saradc_b2c_switch_value` |
| `getmdattr` | Bewegungszonen `m1..m4`: `*_enable`, `*_x/_y/_w/_h`, `*_sensitivity`, `*_threshold` |
| `getmdalarm&-aname=<name>` | `name` = `email`, `emailsnap`, `ftpsnap`, `snap`, `emailrec`, `record`, `ftprec`, `relay`, `preset`, `sound`, `type` |
| `getsmdattr` | `smd_enable` (0/1), `smd_threshold`, Bereich `smd_x/_y/_w/_h` |
| `getsmdex` | `smd_type` (0 Mensch, 1 Mensch und Fahrzeug, 2 Mensch und Haustier, 3 Mensch, Fahrzeug und Haustier), `smd_gthresh` (1-100), `smd_rect` (Rahmen im Bild) |
| `getsmartrackattr` | `smartrack_enable` (Auto-Tracking, 0/1), `smartrack_flag`, `smartrack_timeout`, `smartrack_mode`, `smartrack_f2n`, `smartrack_n2f`, `smartrack_n2ftimeout` |
| `getmotorattr` | `panspeed`, `tiltspeed`, `movehome`, `movesteptimeout`, `presettimeout`, `poweronpresetindex`, `watchpresetindex`, `ptzalarmmask` |
| `getaudioflag`, `getaudioinvolume`, `getaudiooutvolume` | Audio an/aus, Lautstärken, `aec`, `denoise` |
| `getonvifattr` | `ov_enable`, `ov_port`, `ov_subchn`, `ov_snapchn` |
| `getrtspauth`, `getrtspport` | `rtsp_aenable`, `rtspport`, `rtpport` |
| `getimagemaxsize` | `imagesize` (hier `4K169`) |
| `getplanrecattr` | `planrec_enable`, `planrec_chn`, `planrec_time`, `planrec_type` |

Nicht vorhanden (404): `getptzattr`, `getaiattr`, `gettrackattr`, `getsirenattr`, `getprivacyattr`, `getalarmstatus` und weitere. Es gibt also keine Abfrage des aktuellen Alarmzustands, Bewegung und Person kommen nur über ONVIF-Events.

## Schreiben (abgeleitet)

| Zweck | Aufruf |
|---|---|
| KI-Erkennung ein/aus | `cmd=setsmdattr&-smd_enable=0\|1` |
| Erkennungsart, Schwelle, Rahmen | `cmd=setsmdex&-smd_type=0..3&-smd_gthresh=1..100&-smd_rect=0\|1` |
| Alarmart | `cmd=setmdalarm&-aname=type&-switch=on\|off` |
| Auto-Tracking | vermutlich `cmd=setsmartrackattr&-smartrack_enable=0\|1` (nicht aus der Web-Oberfläche belegt, zu testen) |
| Bild spiegeln/drehen | `cmd=setimageattr&-image_type=...` (siehe `web/display.html`) |

## PTZ (abgeleitet aus `web/js/js.js`)

| Zweck | Aufruf |
|---|---|
| Bewegen | `GET /cgi-bin/hi3510/ptzctrl.cgi?-step=0&-act=<aktion>&-speed=<n>` |
| Aktionen | `up`, `down`, `left`, `right`, `home`, `stop`, `zoomin`, `zoomout`, `focusin`, `focusout`, `hscan`, `vscan` |
| Preset anfahren | `GET /cgi-bin/hi3510/preset.cgi?-act=goto&-number=<n>` (nullbasiert) |
| Preset speichern | `GET /cgi-bin/hi3510/preset.cgi?-act=set&-status=1&-number=<n>` |
| Preset löschen | `GET /cgi-bin/hi3510/param.cgi?cmd=preset&-act=set&-status=0&-number=<n>` |

Die Kamera speichert keine Preset-Namen. Namen muss die Integration selbst halten.

## ONVIF (gelesen)

- Profile: `MainStreamProfileToken` (H.264, 3840x2160) und `SecondStreamProfileToken` (H.264, 1280x720).
- PTZ: `GetPresets` liefert pauschal `Preset001` bis `Preset256`, das sagt nichts darüber, welche Slots belegt sind.
- Event-Themen: `RuleEngine/CellMotionDetector/Motion`, `VideoSource/MotionAlarm`, `VideoSource/SignalLoss`, `VideoSource/SignalStandardMismatch`.
  Ein eigenes Personen-Thema gibt es nicht. Wie sich die KI-Erkennung (`smd_*`) in `Motion` niederschlägt, muss mit einer Event-Subscription geprüft werden.
- Die Anmeldung per WS-UsernameToken akzeptiert die PC-Zeit als `Created`, auch wenn `GetSystemDateAndTime` selbst Anmeldung verlangt.
