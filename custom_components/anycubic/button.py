"""Button platform for Anycubic Kobra S1."""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, BUTTON_DEFINITIONS
from .helper.device_info import build_main_device_info


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Anycubic buttons for the given config entry.

    The coordinator instance is read from hass.data and used to create
    one :class:`AnycubicButtonEntity` per definition in ``BUTTON_DEFINITIONS``.
    """
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    # Create regular buttons from definitions but skip the separate
    # pause/resume buttons: we'll expose a single toggle with dynamic text.
    entities = []
    for d in BUTTON_DEFINITIONS:
        if d.get("key") in ("print_pause", "print_resume"):
            continue
        entities.append(AnycubicButtonEntity(coordinator, d))

    # Add a single toggle button for print pause/resume with dynamic label
    entities.append(AnycubicPrintToggleEntity(coordinator))

    async_add_entities(entities)

    # Buttons may trigger axis/print actions; request those topics once so
    # state is available after setup.
    try:
        await coordinator.async_query_topic("axis")
    except Exception:
        _LOGGER.debug("Failed to query axis on button setup")
    try:
        await coordinator.async_query_topic("print")
    except Exception:
        _LOGGER.debug("Failed to query print on button setup")


class AnycubicButtonEntity(CoordinatorEntity, ButtonEntity):
    """Generic button entity for Anycubic actions (homing, print control)."""

    def __init__(self, coordinator, definition: dict):
        """Initialize a button entity from a definition dict.

        Expected definition keys:
        - name: display name
        - key: unique key used for unique_id
        - type: message type (e.g. 'axis' or 'print')
        - action: action name (e.g. 'move', 'stop', 'pause', 'resume')
        - axis: optional axis index for axis actions
        """
        super().__init__(coordinator)
        self.definition = definition
        self._key = definition["key"]
        self._type = definition["type"]
        self._action = definition["action"]
        self._attr_name = definition["name"]
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._key}"
        self._attr_icon = definition.get("icon", "mdi:button-pointer")
        self._attr_has_entity_name = True
        self._axis = definition.get("axis")

    async def async_press(self) -> None:
        """Send the defined control message when the button is pressed."""
        if self._type == "axis":
            msg_type = "axis"
            data = {"axis": self._axis, "move_type": 2, "distance": 0}
        elif self._type == "print":
            msg_type = "print"
            data = {"taskid": "-1"}
        elif self._type == "temperature":
            msg_type = "print"
            data = self.definition.get("data", {})
        else:
            _LOGGER.debug("Unknown button type: %s", self._type)
            return

        try:
            await self.coordinator.async_send_command(msg_type, self._action, data)
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug("Command publish failed for button %s: %s", self._key, err)

    @property
    def device_info(self) -> dict:
        """Return the device information mapping for the device registry."""
        return build_main_device_info(self.coordinator)


class AnycubicPrintToggleEntity(CoordinatorEntity, ButtonEntity):
    """Single button that toggles print pause/resume with dynamic label.

    The button displays 'Pause' when a print is actively running and
    'Resume' when the print is paused. Pressing the button will send the
    corresponding print action to the device.
    """

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Print Pause/Resume"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_print_pause_resume"
        self._attr_has_entity_name = True

    @property
    def _print_state(self) -> dict:
        return self.coordinator.data.get("print", {}).get("data", {})

    @property
    def name(self) -> str:
        # Dynamic display name based on current print state
        state = self._print_state.get("state")
        if state == "paused":
            return "Print Resume"
        return "Print Pause"

    @property
    def icon(self) -> str:
        # Use play icon for resume, pause icon for pause
        state = self._print_state.get("state")
        return "mdi:play" if state == "paused" else "mdi:pause"

    async def async_press(self) -> None:
        # Decide action based on current print state
        state = self._print_state.get("state")
        action = "resume" if state == "paused" else "pause"
        try:
            await self.coordinator.async_send_command("print", action, {"taskid": "-1"})
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug("Command publish failed for print toggle: %s", err)

    @property
    def device_info(self) -> dict:
        """Return device info to attach this button to the integration device."""
        return build_main_device_info(self.coordinator)
