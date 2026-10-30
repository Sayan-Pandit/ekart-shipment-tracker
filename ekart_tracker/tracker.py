import re
import json
import time
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
import requests

from .models import ShipmentDetails, Milestone, ShipmentStatus, sanitize_tracking_id
from .config import config

logger = logging.getLogger(__name__)

class EkartTrackingError(Exception):
    """Exception raised for Ekart tracking errors."""
    pass

class EkartLiveClient:
    """
    Reverse-engineered Ekart Logistics client.
    
    Inspecting the tracking mechanism reveals:
    1. Base URL: https://ekartlogistics.com
    2. Session CSRF Token: Parsed from HTML <meta name="csrf-token" content="...">
    3. Session Cookies: Express session cookie (`session`, `session.sig`, `ab`, `epoctime`)
    4. Modern Tracking Endpoint:
       POST https://ekartlogistics.com/ekartlogistics-web-routes-api/ekartlogistics-web-proxy/trackings/v2
    5. Headers:
       - User-Agent: Modern Chrome User Agent
       - X-User-Agent: <ua> EKCL/website/1
       - csrf-token: <csrf_token>
       - Content-Type: application/json
       - Origin: https://ekartlogistics.com
       - Referer: https://ekartlogistics.com/shipmenttrack/<trackingId>
    6. Body: {"tracking_ids": "<id>"} or {"tracking_ids": ["<id>", ...]}
    7. Response: {"<id>": {"shipmentTrackingDetails": [...], "expectedDeliveryDate": ...}}
    """

    BASE_URL = "https://ekartlogistics.com"
    API_ENDPOINT = f"{BASE_URL}/ekartlogistics-web-routes-api/ekartlogistics-web-proxy/trackings/v2"
    DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

    def __init__(self, timeout: int = 15, cache_ttl: int = 30):
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self.session = requests.Session()
        
        # Configure exponential backoff retry adapter
        try:
            from urllib3.util.retry import Retry
            from requests.adapters import HTTPAdapter
            retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
            adapter = HTTPAdapter(max_retries=retries)
            self.session.mount("https://", adapter)
            self.session.mount("http://", adapter)
        except Exception:
            pass

        self.csrf_token: Optional[str] = None
        self._last_token_time: float = 0
        self._cache: Dict[str, Tuple[float, ShipmentDetails]] = {}

    def refresh_csrf_token(self) -> str:
        """Fetch the Ekart homepage and parse the dynamic CSRF token & session cookies."""
        headers = {
            "User-Agent": self.DEFAULT_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"
        }
        try:
            logger.debug("Requesting Ekart homepage to extract CSRF token...")
            response = self.session.get(self.BASE_URL, headers=headers, timeout=self.timeout)
            response.raise_for_status()

            # Find <meta name="csrf-token" content="..." />
            match = re.search(r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', response.text)
            if not match:
                match = re.search(r'<meta\s+content=["\']([^"\']+)["\']\s+name=["\']csrf-token["\']', response.text)
            
            if not match:
                raise EkartTrackingError("Failed to extract CSRF token from Ekart homepage meta tag.")

            self.csrf_token = match.group(1)
            self._last_token_time = time.time()
            logger.debug("Successfully refreshed Ekart CSRF token: %s", self.csrf_token[:8] + "...")
            return self.csrf_token

        except Exception as e:
            logger.error("Failed to fetch Ekart session and CSRF token: %s", e)
            raise EkartTrackingError(f"Could not connect to Ekart logistics portal: {e}")

    def track(self, tracking_id: str, retry_on_csrf: bool = True, use_cache: bool = True) -> ShipmentDetails:
        """
        Query the live Ekart tracking endpoint for a specific tracking ID.
        Uses TTL cache if queried within cache_ttl seconds.
        """
        clean_id = sanitize_tracking_id(tracking_id)

        # Check in-memory TTL cache
        now = time.time()
        if use_cache and clean_id in self._cache:
            cache_time, cached_details = self._cache[clean_id]
            if now - cache_time < self.cache_ttl:
                logger.debug("Returning cached tracking details for %s (TTL remaining: %.1fs)", clean_id, self.cache_ttl - (now - cache_time))
                return cached_details

        # Ensure we have a valid CSRF token
        if not self.csrf_token or (now - self._last_token_time > 1800):
            self.refresh_csrf_token()

        headers = {
            "User-Agent": self.DEFAULT_UA,
            "X-User-Agent": f"{self.DEFAULT_UA} EKCL/website/1",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "csrf-token": self.csrf_token or "",
            "Origin": self.BASE_URL,
            "Referer": f"{self.BASE_URL}/shipmenttrack/{clean_id}"
        }

        payload = {"tracking_ids": clean_id}

        try:
            resp = self.session.post(
                self.API_ENDPOINT,
                json=payload,
                headers=headers,
                timeout=self.timeout
            )
            
            # Check for CSRF expiry (Ekart returns HTTP 205 with csrfError)
            if resp.status_code == 205 or "EBADCSRFTOKEN" in resp.text:
                if retry_on_csrf:
                    logger.info("CSRF token expired on Ekart server, refreshing and retrying...")
                    self.refresh_csrf_token()
                    return self.track(clean_id, retry_on_csrf=False, use_cache=use_cache)
                else:
                    raise EkartTrackingError("Persistent CSRF validation failure from Ekart server.")

            resp.raise_for_status()
            data = resp.json()
            details = self._parse_response(clean_id, data)
            self._cache[clean_id] = (now, details)
            return details

        except requests.exceptions.RequestException as e:
            logger.error("Network error during Ekart tracking request: %s", e)
            raise EkartTrackingError(f"Network error querying Ekart server: {e}")

    def track_batch(self, tracking_ids: List[str]) -> Dict[str, ShipmentDetails]:
        """
        Query Ekart v2 API for multiple tracking IDs in a single HTTP request.
        """
        if not tracking_ids:
            return {}

        clean_ids = [sanitize_tracking_id(tid) for tid in tracking_ids]
        now = time.time()

        if not self.csrf_token or (now - self._last_token_time > 1800):
            self.refresh_csrf_token()

        headers = {
            "User-Agent": self.DEFAULT_UA,
            "X-User-Agent": f"{self.DEFAULT_UA} EKCL/website/1",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "csrf-token": self.csrf_token or "",
            "Origin": self.BASE_URL,
            "Referer": f"{self.BASE_URL}/"
        }

        payload = {"tracking_ids": clean_ids}

        try:
            resp = self.session.post(self.API_ENDPOINT, json=payload, headers=headers, timeout=self.timeout)
            if resp.status_code == 205 or "EBADCSRFTOKEN" in resp.text:
                self.refresh_csrf_token()
                headers["csrf-token"] = self.csrf_token or ""
                resp = self.session.post(self.API_ENDPOINT, json=payload, headers=headers, timeout=self.timeout)

            resp.raise_for_status()
            data = resp.json()
            results = {}
            for cid in clean_ids:
                d = self._parse_response(cid, data)
                self._cache[cid] = (now, d)
                results[cid] = d
            return results
        except Exception as e:
            logger.error("Batch tracking request failed: %s", e)
            raise EkartTrackingError(f"Batch query failed: {e}")

    def _parse_response(self, tracking_id: str, data: Dict[str, Any]) -> ShipmentDetails:
        """Parse raw Ekart API JSON into a structured ShipmentDetails model."""
        shipment_data = data.get(tracking_id)

        if not shipment_data or not isinstance(shipment_data, dict):
            return ShipmentDetails(
                tracking_id=tracking_id,
                status=ShipmentStatus.UNKNOWN,
                expected_delivery_date=None,
                is_delivered=False,
                fa_shipment=False,
                reached_nearest_hub=False,
                milestones=[],
                raw_data=data
            )

        raw_milestones = shipment_data.get("shipmentTrackingDetails", []) or []
        expected_raw = shipment_data.get("expectedDeliveryDate")
        fa_shipment = bool(shipment_data.get("faShipment", False))
        reached_nearest_hub = bool(shipment_data.get("reachedNearestHub", False))

        expected_delivery_str = None
        if expected_raw and expected_raw > 0:
            try:
                dt = datetime.fromtimestamp(expected_raw / 1000.0)
                expected_delivery_str = dt.strftime("%Y-%m-%d %I:%M %p")
            except Exception:
                expected_delivery_str = str(expected_raw)

        milestones: List[Milestone] = []
        is_delivered = False

        for item in raw_milestones:
            raw_date = item.get("date", 0)
            city = item.get("city", "Facility / Transit Hub")
            status_text = item.get("statusDetails", "Status updated")

            date_str = ""
            time_str = ""
            if raw_date and raw_date > 0:
                try:
                    dt = datetime.fromtimestamp(raw_date / 1000.0)
                    date_str = dt.strftime("%b %d, %Y")
                    time_str = dt.strftime("%I:%M %p")
                except Exception:
                    pass

            if "delivered" in status_text.lower():
                is_delivered = True

            milestones.append(Milestone(
                date_str=date_str,
                time_str=time_str,
                city=city,
                status_details=status_text,
                timestamp=raw_date
            ))

        current_status = ShipmentStatus.UNKNOWN
        if is_delivered:
            current_status = ShipmentStatus.DELIVERED
        elif milestones:
            latest_status = milestones[-1].status_details
            current_status = ShipmentStatus.normalize(latest_status)
        elif reached_nearest_hub:
            current_status = ShipmentStatus.REACHED_HUB

        return ShipmentDetails(
            tracking_id=tracking_id,
            status=current_status,
            expected_delivery_date=expected_delivery_str,
            is_delivered=is_delivered,
            fa_shipment=fa_shipment,
            reached_nearest_hub=reached_nearest_hub,
            milestones=milestones,
            raw_data=shipment_data
        )


class MockEkartClient:
    """
    Simulation client for testing and offline development.
    Advances simulated shipments through realistic lifecycle stages.
    """
    
    SIMULATED_STAGES = [
        ("Order Created", "Seller created shipping label and package is ready", "Mumbai Warehouse", False),
        ("Picked Up", "Shipment picked up by Ekart Logistics courier", "Mumbai Hub", False),
        ("In Transit", "Package arrived at Regional Sort Center", "Pune Hub", False),
        ("Reached Nearest Hub", "Shipment received at destination delivery center", "Bengaluru Hub", False),
        ("Out for Delivery", "Package is out for delivery with Ekart delivery agent", "Bengaluru South Hub", False),
        ("Delivered", "Delivered to recipient with secure OTP verification", "Bengaluru", True),
    ]

    def __init__(self):
        self._states: Dict[str, int] = {}
        self._last_updated: Dict[str, float] = {}

    def get_stage(self, tracking_id: str) -> int:
        return self._states.get(tracking_id, 0)

    def set_stage_from_status(self, tracking_id: str, status_name: str) -> int:
        for idx, (s_name, _, _, _) in enumerate(self.SIMULATED_STAGES):
            if s_name.lower() == status_name.lower():
                self._states[tracking_id] = idx
                return idx
        return self.get_stage(tracking_id)

    def advance_stage(self, tracking_id: str) -> int:
        current = self.get_stage(tracking_id)
        if current < len(self.SIMULATED_STAGES) - 1:
            self._states[tracking_id] = current + 1
            self._last_updated[tracking_id] = time.time()
        return self._states[tracking_id]

    def reset_stage(self, tracking_id: str, stage: int = 0) -> None:
        self._states[tracking_id] = max(0, min(stage, len(self.SIMULATED_STAGES) - 1))
        self._last_updated[tracking_id] = time.time()

    def track(self, tracking_id: str) -> ShipmentDetails:
        stage_idx = self.get_stage(tracking_id)
        status_name, desc, city, is_delivered = self.SIMULATED_STAGES[stage_idx]

        milestones: List[Milestone] = []
        base_time = int(time.time() * 1000) - (len(self.SIMULATED_STAGES) - stage_idx) * 3600 * 1000

        for i in range(stage_idx + 1):
            s_name, s_desc, s_city, s_deliv = self.SIMULATED_STAGES[i]
            m_time = base_time + (i * 3600 * 1000)
            dt = datetime.fromtimestamp(m_time / 1000.0)
            milestones.append(Milestone(
                date_str=dt.strftime("%b %d, %Y"),
                time_str=dt.strftime("%I:%M %p"),
                city=s_city,
                status_details=f"{s_name} - {s_desc}",
                timestamp=m_time
            ))

        expected_dt = datetime.fromtimestamp(time.time() + 86400)
        expected_str = expected_dt.strftime("%Y-%m-%d %I:%M %p")

        return ShipmentDetails(
            tracking_id=tracking_id,
            status=status_name,
            expected_delivery_date=expected_str,
            is_delivered=is_delivered,
            fa_shipment=True,
            reached_nearest_hub=stage_idx >= 3,
            milestones=milestones,
            raw_data={"simulated": True, "stage": stage_idx}
        )


class ShipmentTracker:
    """
    Unified Shipment Tracker supporting both Live Ekart API and Simulation mode.
    """

    def __init__(self, live_client: Optional[EkartLiveClient] = None, mock_client: Optional[MockEkartClient] = None):
        self.live_client = live_client or EkartLiveClient(cache_ttl=config.cache_ttl_seconds)
        self.mock_client = mock_client or MockEkartClient()

    def track(self, tracking_id: str, force_simulated: bool = False, use_cache: bool = True) -> ShipmentDetails:
        clean_id = sanitize_tracking_id(tracking_id)
        if force_simulated or clean_id.startswith("SIM-") or clean_id.startswith("DEMO-"):
            return self.mock_client.track(clean_id)
        
        return self.live_client.track(clean_id, use_cache=use_cache)

    @staticmethod
    def get_tracking_url(tracking_id: str) -> str:
        """Return the official web tracking URL for a package."""
        clean = tracking_id.strip().upper()
        return f"https://ekartlogistics.com/shipmenttrack/{clean}"
