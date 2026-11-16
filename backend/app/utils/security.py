from __future__ import annotations

import ipaddress
from ipaddress import IPv4Address, IPv6Address


class TargetSecurityError(ValueError):
    """Raised when an address is not safe to request."""


def is_unsafe_ip(address: str | IPv4Address | IPv6Address) -> bool:
    """Return True for addresses that must never be scanned by default."""
    ip = ipaddress.ip_address(address)
    if isinstance(ip, IPv6Address) and ip.ipv4_mapped is not None:
        return is_unsafe_ip(ip.ipv4_mapped)
    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return True
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    # RFC 6598 shared address space is not covered consistently by Python's
    # ipaddress flags across supported Python versions.
    if isinstance(ip, IPv4Address) and ipaddress.ip_address("100.64.0.0") <= ip <= ipaddress.ip_address("100.127.255.255"):
        return True
    return False


def assert_safe_ip(address: str | IPv4Address | IPv6Address, *, allow_private: bool = False) -> str:
    ip = ipaddress.ip_address(address)
    if not allow_private and is_unsafe_ip(ip):
        raise TargetSecurityError("target address is not publicly routable")
    return str(ip)
