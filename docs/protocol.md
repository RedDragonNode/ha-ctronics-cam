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

## Schreiben

Antwort bei Erfolg: `[Succeed]set ok.`, bei falschen Parametern `[Error]Param error.` (jeweils HTTP 200).
Einzelne Felder dürfen allein gesendet werden, die übrigen bleiben unverändert.

| Zweck | Aufruf | Stand |
|---|---|---|
| KI-Erkennung ein/aus | `cmd=setsmdattr&-smd_enable=0\|1` | getestet |
| Erkennungsschwelle | `cmd=setsmdex&-smd_gthresh=1..100` | getestet |
| Erkennungsart, Rahmen | `cmd=setsmdex&-smd_type=0..3` und `&-smd_rect=0\|1` | abgeleitet |
| Auto-Tracking | `cmd=setsmartrackattr&-smartrack_enable=0\|1` | getestet |
| Nachtsicht-LEDs | `cmd=setinfrared&-infraredstat=auto\|open\|close` | abgeleitet |
| Bild spiegeln/drehen | `cmd=setimageattr&-flip=on\|off` und `&-mirror=on\|off` | abgeleitet |
| Alarmart | `cmd=setmdalarm&-aname=type&-switch=on\|off` | abgeleitet |

## PTZ

| Zweck | Aufruf | Stand |
|---|---|---|
| Bewegen | `GET /cgi-bin/hi3510/ptzctrl.cgi?-step=0&-act=<aktion>&-speed=<1..8>` | getestet |
| Einzelschritt | wie oben mit `-step=1` | getestet |
| Aktionen | `up`, `down`, `left`, `right`, `home`, `stop`, `hscan`, `vscan` (`zoomin`, `zoomout`, `focusin`, `focusout` stehen in der Web-Oberfläche, die Kamera hat keinen Zoom) | `up/down/left/right/home/stop` getestet |
| Preset anfahren | `GET /cgi-bin/hi3510/preset.cgi?-act=goto&-number=<n>` (nullbasiert) | abgeleitet |
| Preset speichern | `GET /cgi-bin/hi3510/preset.cgi?-act=set&-status=1&-number=<n>` | abgeleitet |
| Preset löschen | `GET /cgi-bin/hi3510/param.cgi?cmd=preset&-act=set&-status=0&-number=<n>` | abgeleitet |

`ptzctrl.cgi` mit `-step=0` bewegt dauerhaft, bis `stop` kommt. Die Kamera speichert keine Preset-Namen, die Integration hält sie selbst.

## Schnappschuss und Speicher

- JPEG in voller Auflösung (rund 350 KB): `GET /tmpfs/auto.jpg`. Dieselbe Adresse nennt ONVIF `GetSnapshotUri`.
- `sdfreespace` und `sdtotalspace` in `getserverinfo` zählen in KiB, `sdstatus` ist `out` ohne Karte und `Ready` mit Karte.

## ONVIF (gelesen)

- Profile: `MainStreamProfileToken` (H.264, 3840x2160) und `SecondStreamProfileToken` (H.264, 1280x720).
- PTZ: `GetPresets` liefert pauschal `Preset001` bis `Preset256`, das sagt nichts darüber, welche Slots belegt sind.
- Event-Themen: `RuleEngine/CellMotionDetector/Motion`, `VideoSource/MotionAlarm`, `VideoSource/SignalLoss`, `VideoSource/SignalStandardMismatch`.
  Ein eigenes Personen-Thema gibt es nicht. Wie sich die KI-Erkennung (`smd_*`) in `Motion` niederschlägt, ist noch zu prüfen.
- Die Anmeldung per WS-UsernameToken akzeptiert die PC-Zeit als `Created`, auch wenn `GetSystemDateAndTime` selbst Anmeldung verlangt.
- **Kein PullPoint:** `CreatePullPointSubscription` wird an jedem Pfad mit "Action Not Implemented" abgelehnt, obwohl `GetServiceCapabilities` `WSPullPointSupport=true` meldet.
- **Push geht:** `wsnt:Subscribe` mit `ConsumerReference` an `/onvif/event_service` (mit `wsa:Action` `.../NotificationProducer/SubscribeRequest`) wird angenommen und liefert `http://<ip>:8080/onvif/Subscription?Idx=<n>`. Die Kamera schickt die Ereignisse dann per HTTP-POST (gSOAP/2.8, `Connection: close`) an die Empfängeradresse, in Home Assistant ein Webhook.
- **Falle: Länge der Empfängeradresse.** Der ONVIF-Dienst der Kamera verträgt nur kurze Adressen. Gemessen mit Home Assistant als Empfänger: Bei 55 Zeichen (`http://192.168.178.53:8123/api/webhook/` plus 16 Zeichen) laufen Abo und Ereignisse einwandfrei. Bei 103 Zeichen (der übliche 64-stellige Webhook-Name) bricht der Dienst beim ersten Ereignis weg: Jede ONVIF-Anfrage, auch `GetDeviceInformation`, läuft dann rund 8 Minuten in einen Fehler oder Zeitfehler, danach ist er wieder da. CGI, RTSP und PTZ laufen währenddessen weiter. Die Integration nutzt deshalb einen 12-stelligen Webhook-Namen und abonniert nur, wenn die Adresse höchstens 60 Zeichen hat.
- **Falle: `Renew` und `Unsubscribe`.** Mit einer 68 Zeichen langen Adresse legten beide den Dienst für Minuten lahm, mit 43 Zeichen gingen sie durch. Die Integration benutzt sie ohnehin nie: Sie legt alle 5 Minuten ein neues Abo mit 10 Minuten Laufzeit an, das alte läuft von selbst ab (die Kamera erlaubt höchstens 10 gleichzeitige Abos).
- **Benachrichtigung bei Bewegung** (Beispiel, Zeit ohne `Z`):

  ```xml
  <wsnt:Notify><wsnt:NotificationMessage>
    <wsnt:SubscriptionReference><wsa5:Address>http://…/onvif/Subscription?Idx=0</wsa5:Address></wsnt:SubscriptionReference>
    <wsnt:Topic Dialect="…ConcreteSet">tns1:RuleEngine/CellMotionDetector/Motion</wsnt:Topic>
    <wsnt:Message><tt:Message UtcTime="2026-10-22T22:49:02" PropertyOperation="Changed">
      <tt:Source>
        <tt:SimpleItem Name="VideoSourceConfigurationToken" Value="VideoIPCameraToken"/>
        <tt:SimpleItem Name="VideoAnalyticsConfigurationToken" Value="VideoAnalyticsToken"/>
        <tt:SimpleItem Name="Rule" Value="MyMotionDetectorRule"/>
      </tt:Source>
      <tt:Data><tt:SimpleItem Name="IsMotion" Value="true"/></tt:Data>
    </tt:Message></wsnt:Message>
  </wsnt:NotificationMessage></wsnt:Notify>
  ```

  Beim Schwenken der Kamera kamen `IsMotion=true` und eine Sekunde später `IsMotion=false`. Das Diagnose-Werkzeug `tools/listen_events.py` zeigt solche Nachrichten roh an.

## Flotte

Alle vier geprüften Kameras melden Modell `C6F0SpZ0N0PpL2` und dieselbe Firmware, die Zugangsdaten sind identisch. Eine Kamera hat eine SD-Karte.
