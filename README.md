# Anycubic Home Assistant Integration (LAN + Cloud)

This custom integration connects Anycubic printers to Home Assistant through:
- LAN (local network)
- Anycubic Cloud (token authentication)

You can pick what fits your setup best: local only, cloud only, or both as separate integration entries.

## Features

- Printer status and sensors (including temperatures, progress, and state)
- Printer control buttons (homing, pause, resume, stop)
- Light, fan, number, switch, and select entities
- Print image/preview support
- Cloud support with token authentication
- Local LAN support via printer IP address

## Installation

### HACS (recommended)

1. Add this repository in HACS via Integrations -> Custom repositories.

[![Add repository to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ViperRNMC&repository=hass-anycubic)

2. Install Anycubic.
3. Restart Home Assistant.
4. Go to Settings -> Devices & Services -> Add Integration.

[![Open your Home Assistant instance and show the integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=anycubic)

### Manual

1. Copy `custom_components/anycubic` into your Home Assistant configuration directory.
2. Restart Home Assistant.
3. Add the integration in Settings -> Devices & Services.

## Configuration

When adding the integration, choose the connection mode:

1. `lan`: connect directly using your printer IP.
2. `cloud`: connect through Anycubic Cloud using a token.

### LAN mode

- Enter your printer IP address.
- The integration will discover the printer and create entities automatically.

### Cloud mode

Supported authentication modes:
- `slicer`
- `android`

Required:
- `user_token` (required)
- `user_device_id` (optional, depends on auth mode)

> [!NOTE]
> For MQTT updates, use a slicer token.

## How to get your user token

### Slicer token method (recommended for MQTT)

> [!IMPORTANT]
> Slicer authentication is usually the best option for MQTT updates and works on both Windows and macOS.

1. Sign in to Anycubic Slicer Next, then fully close the app.
2. Locate your AnycubicSlicerNext config directory.
3. On macOS, you can open it directly from Slicer Next via Help -> Show Configuration Folder.
4. Open `AnycubicSlicerNext.conf` and copy the full `access_token` value (without quotes).
5. Paste this value into `user_token` during Home Assistant setup.

Common file paths:

```text
Windows: %AppData%\AnycubicSlicerNext\AnycubicSlicerNext.conf
Windows: C:\Users\<USERNAME>\AppData\Roaming\AnycubicSlicerNext\AnycubicSlicerNext.conf
macOS: ~/Library/Application Support/AnycubicSlicerNext/AnycubicSlicerNext.conf
```

> [!NOTE]
> If authentication fails, re-open Slicer Next, confirm you are still logged in, copy a fresh token, and try again. You can also use Home Assistant re-auth when the token expires.

## Supported models

This integration targets Anycubic printers with LAN and/or cloud connectivity. It is actively used with modern Kobra generations; please report both working and non-working models in Issues.

## Support

- Documentation: https://github.com/ViperRNMC/hass-anycubic
- Issues: https://github.com/ViperRNMC/hass-anycubic/issues

## Credits

- Original foundation: [berskde](https://github.com/berskde/hass-anycubic)
- Cloud inspiration and practical guidance: [WaresWichall](https://github.com/WaresWichall/hass-anycubic_cloud)

Special thanks to WaresWichall for sharing knowledge, documentation, and cloud integration insights for Anycubic + Home Assistant.

## License

See [LICENSE](LICENSE).
