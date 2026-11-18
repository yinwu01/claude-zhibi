"""Compare HTTPS exit observations from the same address family and endpoint."""
import ipaddress

from .models import ENDPOINT, IPV6_ENDPOINT, timestamp

ENDPOINTS = {4: ENDPOINT, 6: IPV6_ENDPOINT}


def sample(family, reading=None):
    reading = reading or {}
    status = reading.get("status", reading.get("state", "observed" if reading.get("ip") else "not_measured"))
    value = None
    if reading.get("ip"):
        try:
            address = ipaddress.ip_address(reading["ip"])
        except ValueError:
            status = "invalid_response"
        else:
            if address.version == family:
                value = str(address)
            else:
                status = "invalid_response"
    return {"ip": value, "status": status, "at": reading.get("at"),
            "endpoint": reading.get("endpoint")}


def address(reading):
    return reading["ip"] if reading and reading["status"] in ("ok", "observed", "fail") else None


def compare(family, left, right):
    if not (address(left) and address(right)):
        return {"state": "not_measured", "reason": "missing_reading"}
    endpoint = ENDPOINTS[family]
    if any(item["endpoint"] not in (None, endpoint) for item in (left, right)):
        return {"state": "not_measured", "reason": "different_endpoint"}
    if left["at"] and right["at"] and abs((timestamp(left["at"]) - timestamp(right["at"])).total_seconds()) > 300:
        return {"state": "not_measured", "reason": "different_measurement_time"}
    return {"state": "ok" if address(left) == address(right) else "fail"}


def rows(browser, runtime, expected):
    result = []
    for family in ENDPOINTS:
        target = expected.get(family)
        left, right = runtime[family], browser[family]
        result.append({"family": family, "browser": right, "runtime": left, "expected": target,
                       "comparison": compare(family, left, right),
                       "expected_matches": {key: address(reading) == target if address(reading) and target else None
                                            for key, reading in (("runtime", left), ("browser", right))}})
    return result
