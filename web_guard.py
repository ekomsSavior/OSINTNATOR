"""Public-network-only transport for isolated hosted collector processes.

Validate the literal address at socket connect, after DNS resolution. This also
applies to redirects and avoids a separate DNS-check/request rebinding window.
Never installed in the desktop process or the server accepting browser traffic.
"""
import ipaddress
import logging
import os
import socket


def validate_destination(address):
    if not isinstance(address, tuple) or len(address) < 2 or address[1] not in (80, 443):
        raise OSError('Only public HTTP and HTTPS connections are allowed')
    try:
        ip = ipaddress.ip_address(address[0])
    except ValueError as exc:
        raise OSError('Connection must use a resolved public address') from exc
    mapped = getattr(ip, 'ipv4_mapped', None)
    if not ip.is_global or (mapped and not mapped.is_global) or ip.is_multicast or ip.is_reserved:
        raise OSError('Private and special network destinations are unavailable')
    if ip.version==6 and (ip.sixtofour or ip.teredo or ip not in ipaddress.ip_network('2000::/3')):
        raise OSError('IPv6 transition destinations are unavailable')
    for value in os.environ.get('OSINTNATOR_DENY_NETWORKS','').split(','):
        if value.strip() and ip in ipaddress.ip_network(value.strip(),strict=False):
            raise OSError('This infrastructure destination is unavailable')


def restrict_worker():
    os.environ['OSINTNATOR_WEB_WORKER'] = '1'
    os.environ['OSINTNATOR_REMOTE_RENDER'] = '0'
    for key in ('HIBP_API_KEY', 'VIRUSTOTAL_API_KEY', 'OSINTNATOR_VT_ENABLE'):
        os.environ.pop(key, None)
    logging.disable(logging.CRITICAL)
    base = socket.socket

    class PublicSocket(base):
        def connect(self, address):
            validate_destination(address)
            return super().connect(address)

        def connect_ex(self, address):
            validate_destination(address)
            return super().connect_ex(address)

    socket.socket = PublicSocket
