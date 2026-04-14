# Anycubic Kobra MQTT Bericht Attributen Overzicht

Dit document geeft een compleet overzicht van alle MQTT berichten en hun attributen die worden gebruikt door de Anycubic Kobra S1 printer met Ace Pro multicolor box.

## Berichttypen Overzicht

### 1. `print` - Afdrukbaan Besturing
**Acties:** `resume`, `pause`, `stop`, `update`

#### Gemeenschappelijke Attributen:
- `type`: `"print"`
- `action`: `"resume"|"pause"|"stop"|"update"`
- `timestamp`: Unix tijdstempel (milliseconden)
- `msgid`: Unieke bericht-ID
- `data`: Object met afdrukgegevens

#### Afdrukgegevens Attributen:
- `taskid`: Afdrukbericht-ID (`"-1"` wanneer geen actieve afdruk)
- `settings` (alleen bij `update` actie):
  - `aux_fan_speed_pct`: Snelheid hulpventilator in percentage (60, 70)
- `curr_layer`: Huidige laagnummer (0)
- `filename`: Afdrukbestandsnaam (lege tekenreeks wanneer geen bestand)
- `localtask`: Lokale taak naam (lege tekenreeks)
- `print_time`: Totale afdruktijd in seconden (637, 545)
- `progress`: Afdrukvoortgang percentage (100)
- `remain_time`: Resterende tijd in seconden (0)
- `slicer`: Slicer-softwarenaam (`"AnycubicSlicer"`)
- `source_info`: Broninformatie object
  - `plate_index`: Plaatindex (1)
  - `models_from`: Modelbron (0)
  - `software_version`: Slicer versie (`"AnycubicSlicerNext 1.3.7.3 20250928154607"`)
  - `slice_paras_process`: Slice parameters proces (1)
  - `models`: Array van modelobjecten
    - `name`: Modelnaam (`"apple_TV_vesa_mount.stl_id_0_copy_0"`)
    - `file_source`: Bestandsbron (0)
    - `mo_file_id`: Model bestand-ID (-1)
- `supplies_usage`: Gloeidraadgebruik in rauwe eenheden (8279)
- `total_layers`: Totaal aantal lagen (0)

#### Foutstatussen:
- `state`: `"paused"`
- `code`: Foutcode (10107)
- `msg`: Foutbericht in het Chinees (`"耗材不足"` = "Onvoldoende materiaal")

---

### 2. `multiColorBox` - Ace Pro Multicolor Box Besturing
**Acties:** `setDry`, `setAutoFeed`, `refresh`, `getInfo`, `autoUpdateInfo`

#### Gemeenschappelijke Attributen:
- `type`: `"multiColorBox"`
- `action`: `"setDry"|"setAutoFeed"|"refresh"|"getInfo"|"autoUpdateInfo"`
- `timestamp`: Unix tijdstempel (milliseconden)
- `msgid`: Unieke bericht-ID
- `state`: Antwoordstatus (`"success"`, `"done"`)
- `code`: Antwoordcode (200)
- `msg`: Antwoordbericht (`"done"`)
- `data`: Object met box gegevens

#### MultiColorBox Gegevens Attributen:
- `multi_color_box`: Array van box objecten

##### Per Box Attributen:
- `id`: Box-ID (0)
- `status`: Box status (0=inactief, 1=actief)
- `model_id`: Model identifier (0, 40001)
- `auto_feed`: Automatische voeding ingeschakeld (0=uitgeschakeld, 1=ingeschakeld)
- `loaded_slot`: Momenteel geladen slot index (-1=geen, 0-3=slot index)
- `temp`: Box temperatuur in °C (21, 25)
- `humidity`: Box vochtigheid in % (0)

##### Feed Status Object:
- `feed_status`:
  - `code`: Voedingsoperatie code (200)
  - `type`: Voedingstype (-1=geen)
  - `current_status`: Huidige voedingsstatus (-1=geen)
  - `slot_index`: Doelslot index (-1=geen)

##### Drying Status Object:
- `drying_status`:
  - `status`: Droogstatus (0=uit, 1=aan)
  - `target_temp`: Doeldroogtemperatuur in °C (0, 45)
  - `duration`: Droogtijd in minuten (0, 120, 240)
  - `remain_time`: Resterende droogtijd in minuten (0)

##### Slots Array:
- `slots`: Array van slot objecten
  - `index`: Slot index (0-3)
  - `sku`: Gloeidraad SKU (`"AHPLBK-101"`, lege tekenreeks)
  - `type`: Gloeidraadtype (`"PLA"`)
  - `color`: RGB-kleur array ([255,255,0], [33,39,33])
  - `edit_status`: Bewerkingsstatus (0=onbewerkt, 1=bewerkt)
  - `status`: Slot status (5=geladen)
  - `color_group`: Uitgebreide kleurgegevens array ([[255,255,0,255]])
  - `icon_type`: Icon type (0)

---

### 3. `fan` - Ventilator Besturing
**Acties:** `auto`, `query`

#### Gemeenschappelijke Attributen:
- `type`: `"fan"`
- `action`: `"auto"|"query"`
- `timestamp`: Unix tijdstempel (milliseconden)
- `msgid`: Unieke bericht-ID
- `state`: Antwoordstatus (`"done"`)
- `code`: Antwoordcode (200)
- `msg`: Antwoordbericht (lege tekenreeks)
- `data`: Object met ventilatorgegevens

#### Ventilator Gegevens Attributen:
- `taskid`: Taak-ID (`"-1"`)
- `fan_speed_pct`: Snelheid hoofdventilator in percentage (0, 100)
- `aux_fan_speed_pct`: Snelheid hulpventilator in percentage (0, 60, 70)
- `box_fan_level`: Box ventilatorniveau (0, 60)

---

### 4. `light` - LED Verlichting Besturing
**Acties:** `query`

#### Gemeenschappelijke Attributen:
- `type`: `"light"`
- `action`: `"query"`
- `timestamp`: Unix tijdstempel (milliseconden)
- `msgid`: Unieke bericht-ID
- `state`: Antwoordstatus (`"done"`)
- `code`: Antwoordcode (200)
- `msg`: Antwoordbericht (`"done"`)
- `data`: Object met verlichtingsgegevens

#### Verlichtings Gegevens Attributen:
- `lights`: Array van lichtobjecten
  - `type`: Lichttype (2)
  - `status`: Lichtstatus (0=uit, 1=aan)
  - `brightness`: Helderheid percentage (100)

---

### 5. `tempature` - Temperatuur Sensoren
**Acties:** `query`

**Opmerking:** Typo in berichttype - zou "temperature" moeten zijn

#### Gemeenschappelijke Attributen:
- `type`: `"tempature"` (typo)
- `action`: `"query"`
- `timestamp`: Unix tijdstempel (milliseconden)
- `msgid`: Unieke bericht-ID
- `state`: Antwoordstatus (lege tekenreeks)
- `code`: Antwoordcode (200)
- `msg`: Antwoordbericht (lege tekenreeks)
- `data`: Object met temperatuurgegevens

#### Temperatuur Gegevens Attributen:
- `curr_hotbed_temp`: Huidige heetbed temperatuur in °C (18)
- `curr_nozzle_temp`: Huidige nozzle temperatuur in °C (20)
- `target_hotbed_temp`: Doel heetbed temperatuur in °C (0)
- `target_nozzle_temp`: Doel nozzle temperatuur in °C (0)

---

### 6. `peripherie` - Randapparatuur Status
**Acties:** `query`

**Opmerking:** Typo in berichttype - zou "peripherals" moeten zijn

#### Gemeenschappelijke Attributen:
- `type`: `"peripherie"` (typo)
- `action`: `"query"`
- `timestamp`: Unix tijdstempel (milliseconden)
- `msgid`: Unieke bericht-ID
- `state`: Antwoordstatus (`"done"`)
- `code`: Antwoordcode (200)
- `msg`: Antwoordbericht (`"done"`)
- `data`: Object met randapparatuugegevens

#### Randapparatuur Gegevens Attributen:
- `camera`: Camera status (0=verbroken, 1=verbonden)
- `multiColorBox`: Multicolor box status (0=verbroken, 1=verbonden)
- `udisk`: USB disk status (0=niet aanwezig, 1=aanwezig)

---

### 7. `video` - Video/Camera Besturing
**Acties:** `startCapture`, `stopCapture`

#### Gemeenschappelijke Attributen:
- `type`: `"video"`
- `action`: `"startCapture"|"stopCapture"`
- `timestamp`: Unix tijdstempel (milliseconden)
- `msgid`: Unieke bericht-ID
- `state`: Antwoordstatus (`"initSuccess"`, `"pushStopped"`)
- `code`: Antwoordcode (200)
- `msg`: Antwoordbericht (lege tekenreeks)
- `data`: Video gegevens (null voor meeste operaties)

---

### 8. `axis` - As Beweging
**Acties:** `move`

#### Gemeenschappelijke Attributen:
- `type`: `"axis"`
- `action`: `"move"`
- `timestamp`: Unix tijdstempel (milliseconden)
- `msgid`: Unieke bericht-ID
- `state`: Antwoordstatus (`"done"`)
- `code`: Antwoordcode (200)
- `msg`: Antwoordbericht (`"done"`)
- `data`: Bewegingsgegevens (null)

---

### 9. `extfilbox` - Externe Gloeidraad Box
**Acties:** `reportInfo`

#### Gemeenschappelijke Attributen:
- `type`: `"extfilbox"`
- `action`: `"reportInfo"`
- `timestamp`: Unix tijdstempel (milliseconden)
- `msgid`: Unieke bericht-ID
- `state`: Antwoordstatus (`"success"`)
- `code`: Antwoordcode (200)
- `msg`: Antwoordbericht (`"done"`)
- `data`: Object met externe gloeidraadbox gegevens

#### Externe Gloeidraad Box Gegevens Attributen:
- `type`: Gloeidraadtype (`"PLA"`)
- `color`: RGB-kleur array ([0,156,189])
- `loaded`: Geladen slot index (0)
- `status_type`: Statustype (-1=niet aanwezig)
- `current_status`: Huide status (-1=niet aanwezig)

---

## Waardeenbereiken en Betekenissen

### Statuscodes:
- **200**: Succes/OK
- **10107**: Onvoldoende materiaal fout

### Temperatuurwaarden:
- **0**: Uitgeschakeld/uit
- **18-25**: Normale bedrijfstemperaturen in °C
- **45**: Droogtemperatuur in °C

### Ventilatorsnelheden:
- **0**: Uit
- **60-70**: Normale bedrijfssnelheden (%)
- **100**: Maximum snelheid (%)

### Slot Indices:
- **-1**: Geen slot geladen/leeg
- **0-3**: Slot indices voor Ace Pro box

### Booleaanse Waarden:
- **0**: Uitgeschakeld/uit/onwaar
- **1**: Ingeschakeld/aan/waar

### Droog Status:
- **0**: Drogen uit
- **1**: Drogen actief

### Voedings Status Waarden:
- **-1**: Geen operatie/geen
- **200**: Succescodecode

### Randapparatuur Status:
- **0**: Verbroken/niet aanwezig
- **1**: Verbonden/aanwezig

---

## Bericht Stroom Voorbeelden

### Afdrukbaan Levenscyclus:
1. `print` → `update` (instellingen wijzigen)
2. `print` → `pause` (gebruiker pauzeert)
3. `print` → `resume` (gebruiker hervatten)
4. `print` → `stop` (baan voltooid/fout)

### Box Operaties:
1. `multiColorBox` → `getInfo` (query box status)
2. `multiColorBox` → `setDry` (drogen starten/stoppen)
3. `multiColorBox` → `setAutoFeed` (automatische voeding in/uit)
4. `multiColorBox` → `autoUpdateInfo` (slot laadupdate)

### Status Query's:
- `fan` → `query` (ventilatorsnelheden)
- `light` → `query` (LED status)
- `tempature` → `query` (temperaturen)
- `peripherie` → `query` (apparaatstatus)

---

## Opmerkingen

- Alle tijdstempels zijn in Unix milliseconden
- Bericht-ID's (`msgid`) zijn unieke UUID's
- Lege arrays (`[]`) geven aan dat er geen boxes verbonden zijn
- `null` waarden geven aan dat er geen gegevens beschikbaar zijn
- Chinese foutberichten moeten worden vertaald
- Enkele berichttypen hebben typo's ("tempature", "peripherie")</content>
<parameter name="filePath">/Users/viper/Github/anycubic_kobra/mqtt_attributes_overview.md