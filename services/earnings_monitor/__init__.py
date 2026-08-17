"""Local, dependency-light earnings monitoring service."""

from .config import MonitorConfig
from .models import EventState, MonitoredEvent
from .service import EarningsMonitor

__all__ = ["EarningsMonitor", "EventState", "MonitorConfig", "MonitoredEvent"]
