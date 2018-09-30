import time
import socket

import requests
from requests.packages.urllib3 import HTTPConnectionPool, HTTPSConnectionPool
from requests.packages.urllib3.poolmanager import PoolManager, proxy_from_url
from requests.packages.urllib3.connectionpool import VerifiedHTTPSConnection
from requests.adapters import HTTPAdapter
from requests.compat import urlparse

from httplib import HTTPConnection
import errno

DEFAULT_POOLBLOCK = False
SSL_KEYWORDS = ('key_file', 'cert_file', 'cert_reqs', 'ca_certs',
                'ssl_version')

WIN_WSAEINVAL = 10022
WIN_EWOULDBLOCK = 10035
WIN_ECONNRESET = 10054
WIN_EISCONN = 10056
WIN_ENOTCONN = 10057
WIN_EHOSTUNREACH = 10065


def ABORT_FLAG_FUNCTION():
    return False


class TimeoutException(Exception):
    pass


class CanceledException(Exception):
    pass


class AsyncTimeout(float):
    def __repr__(self):
        return '{0}({1})'.format(float(self), self.getConnectTimeout())

    def __str__(self):
        return repr(self)

    @classmethod
    def fromTimeout(cls, t):
        if isinstance(t, AsyncTimeout):
            return t

        try:
            return AsyncTimeout(float(t)) or DEFAULT_TIMEOUT
        except TypeError:
            return DEFAULT_TIMEOUT

    def setConnectTimeout(self, val):
        self._connectTimout = val
        return self

    def getConnectTimeout(self):
        if hasattr(self, '_connectTimout'):
            return self._connectTimout

        return self


DEFAULT_TIMEOUT = AsyncTimeout(10).setConnectTimeout(10)


class AsyncVerifiedHTTPSConnection(VerifiedHTTPSConnection):
    def __init__(self, *args, **kwargs):
        VerifiedHTTPSConnection.__init__(self, *args, **kwargs)
        self._canceled = False
        self.deadline = 0
        self._timeout = AsyncTimeout(DEFAULT_TIMEOUT)

    def _check_timeout(self):
        if time.time() > self.deadline:
            raise TimeoutException('connection timed out')

    def create_connection(self, address, timeout=None, source_address=None):
        """Connect to *address* and return the socket object.

        Convenience function.  Connect to *address* (a 2-tuple ``(host,
        port)``) and return the socket object.  Passing the optional
        *timeout* parameter will set the timeout on the socket instance
        before attempting to connect.  If no *timeout* is supplied, the
        global default timeout setting returned by :func:`getdefaulttimeout`
        is used.  If *source_address* is set it must be a tuple of (host, port)
        for the socket to bind as a source address before making the connection.
        An host of '' or port 0 tells the OS to use the default.
        """
        timeout = AsyncTimeout.fromTimeout(timeout)
        self._timeout = timeout

        host, port = address
        err = None
        for res in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
            af, socktype, proto, canonname, sa = res
            sock = None
            try:
                sock = socket.socket(af, socktype, proto)
                sock.setblocking(False)  # this is obviously critical
                self.deadline = time.time() + timeout.getConnectTimeout()
                # sock.settimeout(timeout)

                if source_address:
                    sock.bind(source_address)
                for msg in self._connect(sock, sa):
                    if self._canceled or ABORT_FLAG_FUNCTION():
                        raise CanceledException('Request canceled')
                sock.setblocking(True)
                return sock

            except socket.error as _:
                err = _
                if sock is not None:
                    sock.close()

        if err is not None:
            raise err
        else:
            raise socket.error("getaddrinfo returns an empty list")

    def _connect(self, sock, sa):
        while not self._canceled and not ABORT_FLAG_FUNCTION():
            time.sleep(0.01)
            self._check_timeout()  # this should be done at the beginning of each loop
            status = sock.connect_ex(sa)
            if not status or status in (errno.EISCONN, WIN_EISCONN):
                break
            elif status in (errno.EINPROGRESS, WIN_EWOULDBLOCK):
                self.deadline = time.time() + self._timeout.getConnectTimeout()
            # elif status in (errno.EWOULDBLOCK, errno.EALREADY) or (os.name == 'nt' and status == errno.WSAEINVAL):
            #     pass
            yield

        if self._canceled or ABORT_FLAG_FUNCTION():
            raise CanceledException('Request canceled')

        error = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if error:
            # TODO: determine when this case can actually happen
            raise socket.error((error,))

    def _new_conn(self):
        sock = self.create_connection(
            address=(self.host, self.port),
            timeout=self.timeout
        )

        return sock

    def cancel(self):
        self._canceled = True


class AsyncHTTPConnection(HTTPConnection):
    def __init__(self, *args, **kwargs):
        HTTPConnection.__init__(self, *args, **kwargs)
        self._canceled = False
        self.deadline = 0

    def cancel(self):
        self._canceled = True


class AsyncHTTPConnectionPool(HTTPConnectionPool):
    def __init__(self, *args, **kwargs):
        HTTPConnectionPool.__init__(self, *args, **kwargs)
        self.connections = []

    def _new_conn(self):
        """
        Return a fresh :class:`httplib.HTTPConnection`.
        """
        self.num_connections += 1

        extra_params = {}
        extra_params['strict'] = self.strict

        conn = AsyncHTTPConnection(host=self.host, port=self.port, timeout=self.timeout.connect_timeout, **extra_params)

        # Backport fix LP #1412545
        if getattr(conn, '_tunnel_host', None):
            # TODO: Fix tunnel so it doesn't depend on self.sock state.
            conn._tunnel()
            # Mark this connection as not reusable
            conn.auto_open = 0

        self.connections.append(conn)

        return conn

    def cancel(self):
        for c in self.connections:
            c.cancel()


class AsyncHTTPSConnectionPool(HTTPSConnectionPool):
    def __init__(self, *args, **kwargs):
        HTTPSConnectionPool.__init__(self, *args, **kwargs)
        self.connections = []

    def _new_conn(self):
        """
        Return a fresh :class:`httplib.HTTPSConnection`.
        """
        self.num_connections += 1

        actual_host = self.host
        actual_port = self.port
        if self.proxy is not None:
            actual_host = self.proxy.host
            actual_port = self.proxy.port

        connection_class = AsyncVerifiedHTTPSConnection

        extra_params = {}
        extra_params['strict'] = self.strict
        connection = connection_class(host=actual_host, port=actual_port, timeout=self.timeout.connect_timeout, **extra_params)

        self.connections.append(connection)

        return self._prepare_conn(connection)

    def cancel(self):
        for c in self.connections:
            c.cancel()


pool_classes_by_scheme = {
    'http': AsyncHTTPConnectionPool,
    'https': AsyncHTTPSConnectionPool,
}


class AsyncPoolManager(PoolManager):
    def _new_pool(self, scheme, host, port, request_context=None):
        """
        Create a new :class:`ConnectionPool` based on host, port and scheme.

        This method is used to actually create the connection pools handed out
        by :meth:`connection_from_url` and companion methods. It is intended
        to be overridden for customization.
        """
        pool_cls = pool_classes_by_scheme[scheme]
        kwargs = self.connection_pool_kw
        if scheme == 'http':
            kwargs = self.connection_pool_kw.copy()
            for kw in SSL_KEYWORDS:
                kwargs.pop(kw, None)

        return pool_cls(host, port, **kwargs)


class AsyncHTTPAdapter(HTTPAdapter):
    def cancel(self):
        for c in self.connections:
            c.cancel()

    def init_poolmanager(self, connections, maxsize, block=DEFAULT_POOLBLOCK):
        """Initializes a urllib3 PoolManager. This method should not be called
        from user code, and is only exposed for use when subclassing the
        :class:`HTTPAdapter <requests.adapters.HTTPAdapter>`.

        :param connections: The number of urllib3 connection pools to cache.
        :param maxsize: The maximum number of connections to save in the pool.
        :param block: Block when no free connections are available.
        """
        # save these values for pickling
        self._pool_connections = connections
        self._pool_maxsize = maxsize
        self._pool_block = block

        self.poolmanager = AsyncPoolManager(num_pools=connections, maxsize=maxsize, block=block)
        self.connections = []

    def get_connection(self, url, proxies=None):
        """Returns a urllib3 connection for the given URL. This should not be
        called from user code, and is only exposed for use when subclassing the
        :class:`HTTPAdapter <requests.adapters.HTTPAdapter>`.

        :param url: The URL to connect to.
        :param proxies: (optional) A Requests-style dictionary of proxies used on this request.
        """
        proxies = proxies or {}
        proxy = proxies.get(urlparse(url.lower()).scheme)

        if proxy:
            proxy_headers = self.proxy_headers(proxy)

            if proxy not in self.proxy_manager:
                self.proxy_manager[proxy] = proxy_from_url(
                    proxy,
                    proxy_headers=proxy_headers,
                    num_pools=self._pool_connections,
                    maxsize=self._pool_maxsize,
                    block=self._pool_block
                )

            conn = self.proxy_manager[proxy].connection_from_url(url)
        else:
            # Only scheme should be lower case
            parsed = urlparse(url)
            url = parsed.geturl()
            conn = self.poolmanager.connection_from_url(url)

        self.connections.append(conn)
        return conn


class Session(requests.Session):
    def __init__(self, *args, **kwargs):
        requests.Session.__init__(self, *args, **kwargs)
        self.mount('https://', AsyncHTTPAdapter())
        self.mount('http://', AsyncHTTPAdapter())

    def cancel(self):
        for v in self.adapters.values():
            v.close()
            v.cancel()
