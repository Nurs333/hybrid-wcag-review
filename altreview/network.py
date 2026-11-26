"""Bounded public-page fetching. Run locally; this is not a multi-tenant URL proxy."""

import ipaddress
import socket
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


def public_url(value, allow_private=False):
    value = value.strip()
    if "://" not in value:
        value = "https://" + value
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Enter a public HTTP or HTTPS URL without embedded credentials.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if allow_private:
        return value
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local")):
        raise ValueError("Private and local network addresses are outside this scanner's scope.")
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0].split("%")[0]).is_global for item in addresses):
        raise ValueError("The address resolves to a private or reserved network.")
    return value


class Redirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        public_url(url)
        return super().redirect_request(request, fp, code, message, headers, url)


def fetch(url, limit=5_000_000):
    url = public_url(url)
    with build_opener(Redirects()).open(Request(url, headers={"User-Agent": "AltReview/2.0"}), timeout=25) as response:
        body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("The response exceeds the download limit.")
        return body
