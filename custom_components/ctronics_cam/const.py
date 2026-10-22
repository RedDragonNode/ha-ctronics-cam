"""Konstanten der Ctronics-4K-Cam-Integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "ctronics_cam"
LOGGER = logging.getLogger(__package__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONF_PTZ_STEP_MS = "ptz_step_ms"
CONF_PRESETS = "presets"

DEFAULT_NAME = "Ctronics 4K Cam"
DEFAULT_PORT = 80
DEFAULT_USERNAME = "admin"
DEFAULT_PTZ_STEP_MS = 400
DEFAULT_PTZ_SPEED = 4
MIN_PTZ_SPEED = 1
MAX_PTZ_SPEED = 8
MAX_PRESET = 64

UPDATE_INTERVAL = timedelta(seconds=30)

RTSP_MAIN_PATH = "11"
RTSP_SUB_PATH = "12"

# ONVIF-Ereignisse: Laufzeit des Abos an der Kamera und Abstand der Erneuerung
EVENT_SUBSCRIPTION_SECONDS = 120
EVENT_RENEW_INTERVAL = timedelta(seconds=EVENT_SUBSCRIPTION_SECONDS // 2)
EVENT_MOTION_TIMEOUT = timedelta(minutes=5)

EVENT_TYPE = f"{DOMAIN}_event"
SIGNAL_PTZ_MOVED = f"{DOMAIN}_ptz_moved_{{}}"

SMD_TYPES = ("human", "human_vehicle", "human_pet", "human_vehicle_pet")
INFRARED_MODES = {"auto": "auto", "on": "open", "off": "close"}
