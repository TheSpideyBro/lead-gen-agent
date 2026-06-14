"""Randomized, VPN/rotation-friendly delays for scraping.

GLOBAL-specific: hammering sources at fixed intervals across countries looks
robotic and trips rate limits. We jitter every wait — longer when switching
target countries, shorter between same-country requests. Never a fixed interval.
"""
import asyncio
import logging
import random

logger = logging.getLogger(__name__)

INTER_COUNTRY_RANGE = (10.0, 30.0)  # seconds between different target countries
INTRA_COUNTRY_RANGE = (3.0, 8.0)    # seconds between same-country requests


async def random_delay(min_s: float, max_s: float) -> float:
    """Sleep a random duration in [min_s, max_s] and return what was waited."""
    wait = random.uniform(min_s, max_s)
    await asyncio.sleep(wait)
    return wait


async def inter_country_delay() -> float:
    wait = await random_delay(*INTER_COUNTRY_RANGE)
    logger.debug("inter-country delay %.1fs", wait)
    return wait


async def intra_country_delay() -> float:
    wait = await random_delay(*INTRA_COUNTRY_RANGE)
    logger.debug("intra-country delay %.1fs", wait)
    return wait
