"""
Wrapper for getifaddrs(3).
"""

import socket
import sys

from collections import namedtuple
from ctypes import *

class sockaddr_in(Structure):
    _fields_ = [
        ('sin_len',     c_uint8),
        ('sin_family',  c_uint8),
        ('sin_port',    c_uint16),
        ('sin_addr',    c_uint8 * 4),
        ('sin_zero',    c_uint8 * 8)
    ]

    def __str__(self):
        try:
            assert self.sin_len >= sizeof(sockaddr_in)
            data = ''.join(map(chr, self.sin_addr))
            return socket.inet_ntop(socket.AF_INET, data)
        except:
            return ''

class sockaddr_in6(Structure):
    _fields_ = [
        ('sin6_len',        c_uint8),
        ('sin6_family',     c_uint8),
        ('sin6_port',       c_uint16),
        ('sin6_flowinfo',   c_uint32),
        ('sin6_addr',       c_uint8 * 16),
        ('sin6_scope_id',   c_uint32)
    ]

    def __str__(self):
        try:
            assert self.sin6_len >= sizeof(sockaddr_in6)
            data = ''.join(map(chr, self.sin6_addr))
            return socket.inet_ntop(socket.AF_INET6, data)
        except:
            return ''

class sockaddr_dl(Structure):
    _fields_ = [
        ('sdl_len',         c_uint8),
        ('sdl_family',      c_uint8),
        ('sdl_index',       c_short),
        ('sdl_type',        c_uint8),
        ('sdl_nlen',        c_uint8),
        ('sdl_alen',        c_uint8),
        ('sdl_slen',        c_uint8),
        ('sdl_data',        c_uint8 * 12)
    ]

    def __str__(self):
        assert self.sdl_len >= sizeof(sockaddr_dl)
        addrdata = self.sdl_data[self.sdl_nlen:self.sdl_nlen+self.sdl_alen]
        return ':'.join('%02x' % x for x in addrdata)

class sockaddr_storage(Structure):
    _fields_ = [
        ('sa_len',      c_uint8),
        ('sa_family',   c_uint8),
        ('sa_data',     c_uint8 * 254)
    ]

class sockaddr(Union):
    _anonymous_ = ('sa_storage', )
    _fields_ = [
        ('sa_storage', sockaddr_storage),
        ('sa_sin', sockaddr_in),
        ('sa_sin6', sockaddr_in6),
        ('sa_sdl', sockaddr_dl),
    ]

    def family(self):
        return self.sa_storage.sa_family

    def __str__(self):
        family = self.family()
        if family == socket.AF_INET:
            return str(self.sa_sin)
        elif family == socket.AF_INET6:
            return str(self.sa_sin6)
        elif family == 18:  # AF_LINK
            return str(self.sa_sdl)
        else:
            print family
            raise NotImplementedError, "address family %d not supported" % family


class ifaddrs(Structure):
    pass
ifaddrs._fields_ = [
    ('ifa_next',        POINTER(ifaddrs)),
    ('ifa_name',        c_char_p),
    ('ifa_flags',       c_uint),
    ('ifa_addr',        POINTER(sockaddr)),
    ('ifa_netmask',     POINTER(sockaddr)),
    ('ifa_dstaddr',     POINTER(sockaddr)),
    ('ifa_data',        c_void_p)
]

# Define constants for the most useful interface flags (from if.h).
IFF_UP            = 0x0001
IFF_BROADCAST     = 0x0002
IFF_LOOPBACK      = 0x0008
IFF_POINTTOPOINT  = 0x0010
IFF_RUNNING       = 0x0040
if sys.platform == 'darwin' or 'bsd' in sys.platform:
    IFF_MULTICAST = 0x8000
elif sys.platform == 'linux':
    IFF_MULTICAST = 0x1000

# Load library implementing getifaddrs and freeifaddrs.
if sys.platform == 'darwin':
    libc = cdll.LoadLibrary('libc.dylib')
else:
    libc = cdll.LoadLibrary('libc.so')

# Tell ctypes the argument and return types for the getifaddrs and
# freeifaddrs functions so it can do marshalling for us.
libc.getifaddrs.argtypes = [POINTER(POINTER(ifaddrs))]
libc.getifaddrs.restype = c_int
libc.freeifaddrs.argtypes = [POINTER(ifaddrs)]


def getifaddrs():
    """
    Get local interface addresses.

    Returns generator of tuples consisting of interface name, interface flags,
    address family (e.g. socket.AF_INET, socket.AF_INET6), address, and netmask.
    The tuple members can also be accessed via the names 'name', 'flags',
    'family', 'address', and 'netmask', respectively.
    """
    # Get address information for each interface.
    addrlist = POINTER(ifaddrs)()
    if libc.getifaddrs(pointer(addrlist)) < 0:
        raise OSError

    X = namedtuple('ifaddrs', 'name flags family address netmask')

    # Iterate through the address information.
    ifaddr = addrlist
    while ifaddr and ifaddr.contents:
        # The following is a hack to workaround a bug in FreeBSD
        # (PR kern/152036) and MacOSX wherein the netmask's sockaddr may be
        # truncated.  Specifically, AF_INET netmasks may have their sin_addr
        # member truncated to the minimum number of bytes necessary to
        # represent the netmask.  For example, a sockaddr_in with the netmask
        # 255.255.254.0 may be truncated to 7 bytes (rather than the normal
        # 16) such that the sin_addr field only contains 0xff, 0xff, 0xfe.
        # All bytes beyond sa_len bytes are assumed to be zero.  Here we work
        # around this truncation by copying the netmask's sockaddr into a
        # zero-filled buffer.
        if ifaddr.contents.ifa_netmask:
            netmask = sockaddr()
            memmove(byref(netmask), ifaddr.contents.ifa_netmask,
                    ifaddr.contents.ifa_netmask.contents.sa_len)
            if netmask.sa_family == socket.AF_INET and netmask.sa_len < sizeof(sockaddr_in):
                netmask.sa_len = sizeof(sockaddr_in)
        else:
            netmask = None

        try:
            yield X(ifaddr.contents.ifa_name,
                    ifaddr.contents.ifa_flags,
                    ifaddr.contents.ifa_addr.contents.family(),
                    str(ifaddr.contents.ifa_addr.contents),
                    str(netmask) if netmask else None)
        except NotImplementedError:
            # Unsupported address family.
            yield X(ifaddr.contents.ifa_name,
                    ifaddr.contents.ifa_flags,
                    None,
                    None,
                    None)
        ifaddr = ifaddr.contents.ifa_next

    # When we are done with the address list, ask libc to free whatever memory
    # it allocated for the list.
    libc.freeifaddrs(addrlist)

__all__ = ['getifaddrs'] + [n for n in dir() if n.startswith('IFF_')]