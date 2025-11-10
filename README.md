# Anycubic WiFi Integration for Home Assistant

This integration allows you to connect Anycubic 3D printers to Home Assistant via your local WiFi network.

## Features

- **Printer status and sensors**: View current printer info, nozzle and hotbed temperature, print job status, and available slots.

- **Buttons**: Control homing functions directly from Home Assistant (Home All, Home XY, Home Z).

- **Light control**: Switch and dim printer and camera lights.

- **Images**: See a thumbnail of the current print job.

- **MQTT communication**: Real-time updates of printer status and print jobs using MQTT.

## Installation

1. Copy the `anycubic_wifi` folder to your Home Assistant `custom_components` directory.
2. Add the integration via the Home Assistant UI and enter the IP address of your Anycubic printer.

### Installation via HACS (recommended)

1. Add this repository to HACS via **Integrations → Custom repositories**

	[![Add repository to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ViperRNMC&repository=hass-anycubic)

2. Install the “Anycubic WiFi” integration
3. Restart Home Assistant
4. Add the integration via **Settings → Devices & Services**

	[![Open your Home Assistant instance and show the integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=anycubic_wifi)

5. Enter the IP address of your Anycubic printer

## Configuration

The integration supports config flow: you can easily add your printer via the Home Assistant interface.

## Supported models

Tested with Anycubic printers that support WiFi and provide an HTTP API.

## Documentation & Support

- [Documentation](https://github.com/ViperRNMC/hass-anycubic)
- [Issue tracker](https://github.com/ViperRNMC/hass-anycubic/issues)

## Credits

Based on the original work by [berskde](https://github.com/berskde/hass-anycubic).

## License

See LICENSE for details.
