#!/usr/bin/env python3
"""
Home Assistant Integration for the AI Companion.
Connects to local HA instance via API for:
- Reading sensor states (temperature, motion, etc.)
- Controlling devices (lights, locks, etc.)
- Executing automations/scripts

Usage:
    from ha.integration import HAIntegration
    
    ha = HAIntegration(config)
    await ha.connect()
    
    # Get sensor state
    temp = await ha.get_state("sensor.temperature")
    
    # Control a light
    await ha.turn_on("light.living_room")
    
    # Check all monitored entities
    states = await ha.get_all_states()
"""

import aiohttp
import asyncio
import logging
import re

logger = logging.getLogger(__name__)


class HAIntegration:
    """Home Assistant API client."""

    def __init__(self, config: dict):
        self.enabled = config.get("enabled", True)
        self.url = config.get("url", "http://192.168.1.x:8123")
        self.token = config.get("token", "")
        
        if not self.enabled or not self.token:
            logger.warning("HA integration disabled or no token configured.")
            return

        self.base_url = f"{self.url}/api"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        self.session = None
        
        # Monitored entities
        self.watch_entities = config.get("watch_entities", [])
        self.entity_states = {}

    async def connect(self) -> bool:
        """Test connection to HA. Returns True if connected."""
        if not self.enabled:
            return False

        try:
            self.session = aiohttp.ClientSession(headers=self.headers)
            async with self.session.get(f"{self.base_url}/states") as resp:
                if resp.status == 200:
                    logger.info("Connected to Home Assistant.")
                    return True
                else:
                    logger.error(f"HA connection failed: {resp.status}")
                    return False
        except Exception as e:
            logger.error(f"HA connection error: {e}")
            return False

    async def get_state(self, entity_id: str) -> str:
        """Get the state of an entity.
        
        Args:
            entity_id: e.g., "sensor.temperature", "light.living_room"
            
        Returns:
            State string (e.g., "22.5", "on", "locked")
        """
        try:
            async with self.session.get(
                f"{self.base_url}/states/{entity_id}"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    state = data.get("state", "unknown")
                    attrs = data.get("attributes", {})
                    
                    # Format state nicely
                    if "unit_of_measurement" in attrs:
                        return f"{state} {attrs['unit_of_measurement']}"
                    return str(state)
                return "unknown"
        except Exception as e:
            logger.error(f"HA get_state error for {entity_id}: {e}")
            return "unknown"

    async def get_all_states(self) -> dict:
        """Get all entity states."""
        try:
            async with self.session.get(f"{self.base_url}/states") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    states = {}
                    for item in data:
                        states[item["entity_id"]] = {
                            "state": item["state"],
                            "attributes": item.get("attributes", {}),
                        }
                    return states
                return {}
        except Exception as e:
            logger.error(f"HA get_all_states error: {e}")
            return {}

    async def get_entity_attributes(self, entity_id: str) -> dict:
        """Get attributes of an entity."""
        try:
            async with self.session.get(
                f"{self.base_url}/states/{entity_id}"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("attributes", {})
                return {}
        except Exception as e:
            logger.error(f"HA get_attributes error: {e}")
            return {}

    async def turn_on(self, entity_id: str, area=None) -> bool:
        """Turn on a light or switch."""
        domain, object_id = entity_id.split(".")
        service_data = {}
        if area:
            service_data["area_id"] = area
        
        try:
            async with self.session.post(
                f"{self.base_url}/services/{domain}/turn_on",
                json={"entity_id": entity_id},
            ) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"HA turn_on error: {e}")
            return False

    async def turn_off(self, entity_id: str) -> bool:
        """Turn off a light or switch."""
        try:
            async with self.session.post(
                f"{self.base_url}/services/light/turn_off",
                json={"entity_id": entity_id},
            ) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"HA turn_off error: {e}")
            return False

    async def set_light_color(self, entity_id: str, color: dict) -> bool:
        """Set RGB light color.
        
        Args:
            entity_id: e.g., "light.living_room"
            color: dict with "rgb_color": [r, g, b] or "transition": seconds
        """
        try:
            async with self.session.post(
                f"{self.base_url}/services/light/turn_on",
                json={"entity_id": entity_id, **color},
            ) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"HA set_color error: {e}")
            return False

    async def execute_script(self, script_id: str) -> bool:
        """Execute a HA script."""
        try:
            async with self.session.post(
                f"{self.base_url}/services/script/turn_on",
                json={"entity_id": script_id},
            ) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"HA execute_script error: {e}")
            return False

    async def call_service(self, domain: str, service: str, **kwargs) -> bool:
        """Call any HA service."""
        try:
            async with self.session.post(
                f"{self.base_url}/services/{domain}/{service}",
                json=kwargs,
            ) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"HA call_service error: {e}")
            return False

    async def get_areas(self) -> dict:
        """Get all areas and their IDs."""
        try:
            async with self.session.get(f"{self.base_url}/areas") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    areas = {}
                    for area in data:
                        areas[area["name"].lower()] = area["id"]
                    return areas
                return {}
        except Exception as e:
            logger.error(f"HA get_areas error: {e}")
            return {}

    async def search_entities(self, query: str) -> list:
        """Search for entities by name/pattern.
        
        Args:
            query: Search string, e.g., "living room light"
            
        Returns:
            List of matching entity_ids
        """
        all_states = await self.get_all_states()
        matches = []
        
        query_lower = query.lower()
        for entity_id, info in all_states.items():
            name = info.get("attributes", {}).get("friendly_name", "").lower()
            if query_lower in name or query_lower in entity_id:
                matches.append(entity_id)
        
        return matches

    async def check_motion(self) -> bool:
        """Check if any motion sensor is active."""
        states = await self.get_all_states()
        for entity_id, info in states.items():
            if "motion" in entity_id and info["state"] == "on":
                return True
        return False

    async def close(self):
        """Close the HA session."""
        if self.session:
            await self.session.close()
