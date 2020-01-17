#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
websocket - WebSocket client library for Python

Copyright (C) 2010 Hiroki Ohtani(liris)

    This library is free software; you can redistribute it and/or
    modify it under the terms of the GNU Lesser General Public
    License as published by the Free Software Foundation; either
    version 2.1 of the License, or (at your option) any later version.

    This library is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
    Lesser General Public License for more details.

    You should have received a copy of the GNU Lesser General Public
    License along with this library; if not, write to the Free Software
    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""
from __future__ import unicode_literals
from future import standard_library
standard_library.install_aliases()
from builtins import str
from builtins import chr
from builtins import range
from builtins import object
import socket

try:
    import ssl
    from ssl import SSLError
    HAVE_SSL = True
except ImportError:
    class SSLError(Exception):
        """
        Dummy class of SSLError for ssl none-support environment.
        """
        pass

    HAVE_SSL = False

from urllib.parse import urlparse
import os
import array
import struct
import uuid
import hashlib
import base64
import threading
import logging
import traceback
import sys

from . import utils, app

###############################################################################

LOG = logging.getLogger('PLEX.websocket')

###############################################################################

"""
websocket python client.
=========================

This version support only hybi-13.
Please see http://tools.ietf.org/html/rfc6455 for protocol.
"""


# websocket supported version.
VERSION = 13

# closing frame status codes.
STATUS_NORMAL = 1000
STATUS_GOING_AWAY = 1001
STATUS_PROTOCOL_ERROR = 1002
STATUS_UNSUPPORTED_DATA_TYPE = 1003
STATUS_STATUS_NOT_AVAILABLE = 1005
STATUS_ABNORMAL_CLOSED = 1006
STATUS_INVALID_PAYLOAD = 1007
STATUS_POLICY_VIOLATION = 1008
STATUS_MESSAGE_TOO_BIG = 1009
STATUS_INVALID_EXTENSION = 1010
STATUS_UNEXPECTED_CONDITION = 1011
STATUS_TLS_HANDSHAKE_ERROR = 1015


class WebSocketException(Exception):
    """
    websocket exeception class.
    """
    pass


class WebSocketConnectionClosedException(WebSocketException):
    """
    If remote host closed the connection or some network error happened,
    this exception will be raised.
    """
    pass


class WebSocketTimeoutException(WebSocketException):
    """
    WebSocketTimeoutException will be raised at socket timeout during read and
    write data.
    """
    pass


class WebsocketRedirect(WebSocketException):
    """
    WebsocketRedirect will be raised if a status code 301 is returned
    The Exception will be instantiated with a dict containing all response
    headers; which should contain the redirect address under the key 'location'

    Access the headers via the attribute headers
    """
    def __init__(self, headers):
        self.headers = headers
        super(WebsocketRedirect, self).__init__()


DEFAULT_TIMEOUT = None
TRACE_ENABLED = False


def enable_trace(tracable):
    """
    turn on/off the tracability.

    tracable: boolean value. if set True, tracability is enabled.
    """
    global TRACE_ENABLED
    TRACE_ENABLED = tracable
    if tracable:
        if not LOG.handlers:
            LOG.addHandler(logging.StreamHandler())
        LOG.setLevel(logging.DEBUG)


def setdefaulttimeout(timeout):
    """
    Set the global timeout setting to connect.

    timeout: default socket timeout time. This value is second.
    """
    global DEFAULT_TIMEOUT
    DEFAULT_TIMEOUT = timeout


def getdefaulttimeout():
    """
    Return the global timeout setting(second) to connect.
    """
    return DEFAULT_TIMEOUT


def _parse_url(url):
    """
    parse url and the result is tuple of
    (hostname, port, resource path and the flag of secure mode)

    url: url string.
    """
    if ":" not in url:
        raise ValueError("url is invalid")

    scheme, url = url.split(":", 1)

    parsed = urlparse(url, scheme="http")
    if parsed.hostname:
        hostname = parsed.hostname
    else:
        raise ValueError("hostname is invalid")
    port = 0
    if parsed.port:
        port = parsed.port

    is_secure = False
    if scheme == "ws" or scheme == 'http':
        if not port:
            port = 80
    elif scheme == "wss" or scheme == 'https':
        is_secure = True
        if not port:
            port = 443
    else:
        raise ValueError("scheme %s is invalid" % scheme)

    if parsed.path:
        resource = parsed.path
    else:
        resource = "/"

    if parsed.query:
        resource += "?" + parsed.query

    return (hostname, port, resource, is_secure)


def create_connection(url, timeout=None, **options):
    """
    connect to url and return websocket object.

    Connect to url and return the WebSocket object.
    Passing optional timeout parameter will set the timeout on the socket.
    If no timeout is supplied, the global default timeout setting returned by
    getdefauttimeout() is used.
    You can customize using 'options'.
    If you set "header" list object, you can set your own custom header.

    >>> conn = create_connection("ws://echo.websocket.org/",
         ...     header=["User-Agent: MyProgram",
         ...             "x-custom: header"])


    timeout: socket timeout time. This value is integer.
             if you set None for this value, it means "use DEFAULT_TIMEOUT
             value"

    options: current support option is only "header".
             if you set header as dict value, the custom HTTP headers are added
    """
    sockopt = options.get("sockopt", [])
    sslopt = options.get("sslopt", {})
    websock = WebSocket(sockopt=sockopt, sslopt=sslopt)
    websock.settimeout(timeout if timeout is not None else DEFAULT_TIMEOUT)
    websock.connect(url, **options)
    return websock


_MAX_INTEGER = (1 << 32) - 1
_AVAILABLE_KEY_CHARS = list(range(0x21, 0x2f + 1)) + list(range(0x3a, 0x7e + 1))
_MAX_CHAR_BYTE = (1 << 8) - 1

# ref. Websocket gets an update, and it breaks stuff.
# http://axod.blogspot.com/2010/06/websocket-gets-update-and-it-breaks.html


def _create_sec_websocket_key():
    uid = uuid.uuid4()
    return base64.encodestring(uid.bytes).strip()


_HEADERS_TO_CHECK = {"upgrade": "websocket", "connection": "upgrade"}


class ABNF(object):
    """
    ABNF frame class.
    see http://tools.ietf.org/html/rfc5234
    and http://tools.ietf.org/html/rfc6455#section-5.2
    """

    # operation code values.
    OPCODE_CONT = 0x0
    OPCODE_TEXT = 0x1
    OPCODE_BINARY = 0x2
    OPCODE_CLOSE = 0x8
    OPCODE_PING = 0x9
    OPCODE_PONG = 0xa

    # available operation code value tuple
    OPCODES = (OPCODE_CONT, OPCODE_TEXT, OPCODE_BINARY, OPCODE_CLOSE,
               OPCODE_PING, OPCODE_PONG)

    # opcode human readable string
    OPCODE_MAP = {
        OPCODE_CONT: "cont",
        OPCODE_TEXT: "text",
        OPCODE_BINARY: "binary",
        OPCODE_CLOSE: "close",
        OPCODE_PING: "ping",
        OPCODE_PONG: "pong"
    }

    # data length threashold.
    LENGTH_7 = 0x7d
    LENGTH_16 = 1 << 16
    LENGTH_63 = 1 << 63

    def __init__(self, fin=0, rsv1=0, rsv2=0, rsv3=0,
                 opcode=OPCODE_TEXT, mask=1, data=""):
        """
        Constructor for ABNF.
        please check RFC for arguments.
        """
        self.fin = fin
        self.rsv1 = rsv1
        self.rsv2 = rsv2
        self.rsv3 = rsv3
        self.opcode = opcode
        self.mask = mask
        self.data = data
        self.get_mask_key = os.urandom

    def __str__(self):
        return "fin=" + str(self.fin) \
               + " opcode=" + str(self.opcode) \
               + " data=" + str(self.data)

    @staticmethod
    def create_frame(data, opcode):
        """
        create frame to send text, binary and other data.

        data: data to send. This is string value(byte array).
            if opcode is OPCODE_TEXT and this value is uniocde,
            data value is conveted into unicode string, automatically.

        opcode: operation code. please see OPCODE_XXX.
        """
        if opcode == ABNF.OPCODE_TEXT and isinstance(data, str):
            data = utils.try_encode(data)
        # mask must be set if send data from client
        return ABNF(1, 0, 0, 0, opcode, 1, data)

    def format(self):
        """
        format this object to string(byte array) to send data to server.
        """
        if any(x not in (0, 1) for x in [self.fin, self.rsv1, self.rsv2, self.rsv3]):
            raise ValueError("not 0 or 1")
        if self.opcode not in ABNF.OPCODES:
            raise ValueError("Invalid OPCODE")
        length = len(self.data)
        if length >= ABNF.LENGTH_63:
            raise ValueError("data is too long")

        frame_header = chr(self.fin << 7 |
                           self.rsv1 << 6 | self.rsv2 << 5 | self.rsv3 << 4 |
                           self.opcode)
        if length < ABNF.LENGTH_7:
            frame_header += chr(self.mask << 7 | length)
        elif length < ABNF.LENGTH_16:
            frame_header += chr(self.mask << 7 | 0x7e)
            frame_header += struct.pack("!H", length)
        else:
            frame_header += chr(self.mask << 7 | 0x7f)
            frame_header += struct.pack("!Q", length)

        if not self.mask:
            return frame_header + self.data
        else:
            mask_key = self.get_mask_key(4)
            return frame_header + self._get_masked(mask_key)

    def _get_masked(self, mask_key):
        s = ABNF.mask(mask_key, self.data)
        return mask_key + "".join(s)

    @staticmethod
    def mask(mask_key, data):
        """
        mask or unmask data. Just do xor for each byte

        mask_key: 4 byte string(byte).

        data: data to mask/unmask.
        """
        _m = array.array("B", mask_key)
        _d = array.array("B", data.encode())
        for i, _v in enumerate(_d):
            _d[i] ^= _m[i % 4]
        return ''.join(_d)


class WebSocket(object):
    """
    Low level WebSocket interface.
    This class is based on
      The WebSocket protocol draft-hixie-thewebsocketprotocol-76
      http://tools.ietf.org/html/draft-hixie-thewebsocketprotocol-76

    We can connect to the websocket server and send/recieve data.
    The following example is a echo client.

    >>> import websocket
    >>> ws = websocket.WebSocket()
    >>> ws.connect("ws://echo.websocket.org")
    >>> ws.send("Hello, Server")
    >>> ws.recv()
    'Hello, Server'
    >>> ws.close()

    get_mask_key: a callable to produce new mask keys, see the set_mask_key
      function's docstring for more details
    sockopt: values for socket.setsockopt.
        sockopt must be tuple and each element is argument of sock.setscokopt.
    sslopt: dict object for ssl socket option.
    """

    def __init__(self, get_mask_key=None, sockopt=None, sslopt=None):
        """
        Initalize WebSocket object.
        """
        if sockopt is None:
            sockopt = []
        if sslopt is None:
            sslopt = {}
        self.connected = False
        self.sock = socket.socket()
        for opts in sockopt:
            self.sock.setsockopt(*opts)
        self.sslopt = sslopt
        self.get_mask_key = get_mask_key
        # Buffers over the packets from the layer beneath until desired amount
        # bytes of bytes are received.
        self._recv_buffer = []
        # These buffer over the build-up of a single frame.
        self._frame_header = None
        self._frame_length = None
        self._frame_mask = None
        self._cont_data = None

    def fileno(self):
        """
        Returns sock.fileno()
        """
        return self.sock.fileno()

    def set_mask_key(self, func):
        """
        set function to create musk key. You can custumize mask key generator.
        Mainly, this is for testing purpose.

        func: callable object. the fuct must 1 argument as integer.
              The argument means length of mask key.
              This func must be return string(byte array),
              which length is argument specified.
        """
        self.get_mask_key = func

    def gettimeout(self):
        """
        Get the websocket timeout(second).
        """
        return self.sock.gettimeout()

    def settimeout(self, timeout):
        """
        Set the timeout to the websocket.

        timeout: timeout time(second).
        """
        self.sock.settimeout(timeout)

    timeout = property(gettimeout, settimeout)

    def connect(self, url, **options):
        """
        Connect to url. url is websocket url scheme. ie. ws://host:port/resource
        You can customize using 'options'.
        If you set "header" dict object, you can set your own custom header.

        >>> ws = WebSocket()
        >>> ws.connect("ws://echo.websocket.org/",
                ...     header={"User-Agent: MyProgram",
                ...             "x-custom: header"})

        timeout: socket timeout time. This value is integer.
                 if you set None for this value,
                 it means "use DEFAULT_TIMEOUT value"

        options: current support option is only "header".
                 if you set header as dict value,
                 the custom HTTP headers are added.

        """
        hostname, port, resource, is_secure = _parse_url(url)
        # TODO: we need to support proxy
        self.sock.connect((hostname, port))
        if is_secure:
            if HAVE_SSL:
                if self.sslopt is None:
                    sslopt = {}
                else:
                    sslopt = self.sslopt
                self.sock = ssl.wrap_socket(self.sock, **sslopt)
            else:
                raise WebSocketException("SSL not available.")

        self._handshake(hostname, port, resource, **options)

    def _handshake(self, host, port, resource, **options):
        headers = []
        headers.append("GET %s HTTP/1.1" % resource)
        headers.append("Upgrade: websocket")
        headers.append("Connection: Upgrade")
        if port == 80:
            hostport = host
        else:
            hostport = "%s:%d" % (host, port)
        headers.append("Host: %s" % hostport)

        if "origin" in options:
            headers.append("Origin: %s" % options["origin"])
        else:
            headers.append("Origin: http://%s" % hostport)

        key = _create_sec_websocket_key().decode('utf-8')
        headers.append("Sec-WebSocket-Key: %s" % key)
        headers.append("Sec-WebSocket-Version: %s" % VERSION)
        if "header" in options:
            headers.extend(options["header"])

        headers.append("")
        headers.append("")

        header_str = "\r\n".join(headers)
        self._send(header_str.encode())
        if TRACE_ENABLED:
            LOG.debug("--- request header ---")
            LOG.debug(header_str)
            LOG.debug("-----------------------")

        status, resp_headers = self._read_headers()
        if status == 301:
            # Redirect
            raise WebsocketRedirect(resp_headers)
        if status != 101:
            self.close()
            raise WebSocketException("Handshake Status %d" % status)

        success = self._validate_header(resp_headers, key)
        if not success:
            self.close()
            raise WebSocketException("Invalid WebSocket Header")

        self.connected = True

    @staticmethod
    def _validate_header(headers, key):
        for k, v in _HEADERS_TO_CHECK.items():
            r = headers.get(k, None)
            if not r:
                return False
            r = r.lower()
            if v != r:
                return False

        result = headers.get("sec-websocket-accept", None)
        if not result:
            return False
        result = result.lower()

        value = (key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()
        hashed = base64.encodestring(hashlib.sha1(value).digest()).strip().lower().decode('utf-8')
        return hashed == result

    def _read_headers(self):
        status = None
        headers = {}
        if TRACE_ENABLED:
            LOG.debug("--- response header ---")

        while True:
            line = self._recv_line()
            if line == "\r\n":
                break
            line = line.strip()
            if TRACE_ENABLED:
                LOG.debug(line)
            if not status:
                status_info = line.split(" ", 2)
                status = int(status_info[1])
            else:
                kv = line.split(":", 1)
                if len(kv) == 2:
                    key, value = kv
                    headers[key.lower()] = value.strip().lower()
                else:
                    raise WebSocketException("Invalid header")

        if TRACE_ENABLED:
            LOG.debug("-----------------------")

        return status, headers

    def send(self, payload, opcode=ABNF.OPCODE_TEXT):
        """
        Send the data as string.

        payload: Payload must be utf-8 string or unicoce,
                  if the opcode is OPCODE_TEXT.
                  Otherwise, it must be string(byte array)

        opcode: operation code to send. Please see OPCODE_XXX.
        """
        frame = ABNF.create_frame(payload, opcode)
        if self.get_mask_key:
            frame.get_mask_key = self.get_mask_key
        data = frame.format()
        length = len(data)
        if TRACE_ENABLED:
            LOG.debug("send: %s", repr(data))
        while data:
            l = self._send(data)
            data = data[l:]
        return length

    def send_binary(self, payload):
        """
        send the payload
        """
        return self.send(payload, ABNF.OPCODE_BINARY)

    def ping(self, payload=""):
        """
        send ping data.

        payload: data payload to send server.
        """
        self.send(payload, ABNF.OPCODE_PING)

    def pong(self, payload):
        """
        send pong data.

        payload: data payload to send server.
        """
        self.send(payload, ABNF.OPCODE_PONG)

    def recv(self):
        """
        Receive string data(byte array) from the server.

        return value: string(byte array) value.
        """
        _, data = self.recv_data()
        return data

    def recv_data(self):
        """
        Recieve data with operation code.

        return  value: tuple of operation code and string(byte array) value.
        """
        while True:
            frame = self.recv_frame()
            if not frame:
                # handle error:
                # 'NoneType' object has no attribute 'opcode'
                raise WebSocketException("Not a valid frame %s" % frame)
            elif frame.opcode in (ABNF.OPCODE_TEXT, ABNF.OPCODE_BINARY, ABNF.OPCODE_CONT):
                if frame.opcode == ABNF.OPCODE_CONT and not self._cont_data:
                    raise WebSocketException("Illegal frame")
                if self._cont_data:
                    self._cont_data[1] += frame.data
                else:
                    self._cont_data = [frame.opcode, frame.data]
                if frame.fin:
                    data = self._cont_data
                    self._cont_data = None
                    return data
            elif frame.opcode == ABNF.OPCODE_CLOSE:
                self.send_close()
                return (frame.opcode, None)
            elif frame.opcode == ABNF.OPCODE_PING:
                self.pong(frame.data)

    def recv_frame(self):
        """
        recieve data as frame from server.

        return value: ABNF frame object.
        """
        # Header
        if self._frame_header is None:
            self._frame_header = self._recv_strict(2)
        b1 = ord(self._frame_header[0])
        fin = b1 >> 7 & 1
        rsv1 = b1 >> 6 & 1
        rsv2 = b1 >> 5 & 1
        rsv3 = b1 >> 4 & 1
        opcode = b1 & 0xf
        b2 = ord(self._frame_header[1])
        has_mask = b2 >> 7 & 1
        # Frame length
        if self._frame_length is None:
            length_bits = b2 & 0x7f
            if length_bits == 0x7e:
                length_data = self._recv_strict(2)
                self._frame_length = struct.unpack("!H", length_data)[0]
            elif length_bits == 0x7f:
                length_data = self._recv_strict(8)
                self._frame_length = struct.unpack("!Q", length_data)[0]
            else:
                self._frame_length = length_bits
        # Mask
        if self._frame_mask is None:
            self._frame_mask = self._recv_strict(4) if has_mask else ""
        # Payload
        payload = self._recv_strict(self._frame_length)
        if has_mask:
            payload = ABNF.mask(self._frame_mask, payload)
        # Reset for next frame
        self._frame_header = None
        self._frame_length = None
        self._frame_mask = None
        return ABNF(fin, rsv1, rsv2, rsv3, opcode, has_mask, payload)


    def send_close(self, status=STATUS_NORMAL, reason=""):
        """
        send close data to the server.

        status: status code to send. see STATUS_XXX.

        reason: the reason to close. This must be string.
        """
        if status < 0 or status >= ABNF.LENGTH_16:
            raise ValueError("code is invalid range")
        self.send(struct.pack('!H', status).decode('utf-8', 'ignore') + reason, ABNF.OPCODE_CLOSE)

    def close(self, status=STATUS_NORMAL, reason=""):
        """
        Close Websocket object

        status: status code to send. see STATUS_XXX.

        reason: the reason to close. This must be string.
        """
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        self._closeInternal()

    def _closeInternal(self):
        self.connected = False
        self.sock.close()

    def _send(self, data):
        try:
            return self.sock.send(data)
        except socket.timeout as e:
            raise WebSocketTimeoutException(e.args[0])
        except Exception as e:
            if "timed out" in e.args[0]:
                raise WebSocketTimeoutException(e.args[0])
            else:
                raise e

    def _recv(self, bufsize):
        try:
            bytes_ = self.sock.recv(bufsize)
        except socket.timeout as e:
            raise WebSocketTimeoutException(e.args[0])
        except SSLError as e:
            if e.args[0] == "The read operation timed out":
                raise WebSocketTimeoutException(e.args[0])
            else:
                raise
        if not bytes_:
            raise WebSocketConnectionClosedException()
        return bytes_

    def _recv_strict(self, bufsize):
        shortage = bufsize - sum(len(x) for x in self._recv_buffer)
        while shortage > 0:
            bytes_ = self._recv(shortage).decode('utf-8', 'ignore')
            self._recv_buffer.append(bytes_)
            shortage -= len(bytes_)
        unified = "".join(self._recv_buffer)
        if shortage == 0:
            self._recv_buffer = []
            return unified
        else:
            self._recv_buffer = [unified[bufsize:]]
            return unified[:bufsize]

    def _recv_line(self):
        line = []
        while True:
            c = self._recv(1).decode('utf-8', 'ignore')
            line.append(c)
            if c == "\n":
                break
        return "".join(line)


class WebSocketApp(object):
    """
    Higher level of APIs are provided.
    The interface is like JavaScript WebSocket object.
    """
    def __init__(self, url, header=None,
                 on_open=None, on_message=None, on_error=None,
                 on_close=None, keep_running=True, get_mask_key=None):
        """
        url: websocket url.
        header: custom header for websocket handshake.
        on_open: callable object which is called at opening websocket.
          this function has one argument. The arugment is this class object.
        on_message: callbale object which is called when recieved data.
         on_message has 2 arguments.
         The 1st arugment is this class object.
         The passing 2nd arugment is utf-8 string which we get from the server.
       on_error: callable object which is called when we get error.
         on_error has 2 arguments.
         The 1st arugment is this class object.
         The passing 2nd arugment is exception object.
       on_close: callable object which is called when closed the connection.
         this function has one argument. The arugment is this class object.
       keep_running: a boolean flag indicating whether the app's main loop should
         keep running, defaults to True
       get_mask_key: a callable to produce new mask keys, see the WebSocket.set_mask_key's
         docstring for more information
        """
        self.url = url
        self.header = [] if header is None else header
        self.on_open = on_open
        self.on_message = on_message
        self.on_error = on_error
        self.on_close = on_close
        self.keep_running = keep_running
        self.get_mask_key = get_mask_key
        self.sock = None

    def send(self, data, opcode=ABNF.OPCODE_TEXT):
        """
        send message.
        data: message to send. If you set opcode to OPCODE_TEXT, data must be utf-8 string or unicode.
        opcode: operation code of data. default is OPCODE_TEXT.
        """
        if self.sock.send(data, opcode) == 0:
            raise WebSocketConnectionClosedException()

    def close(self):
        """
        close websocket connection.
        """
        self.keep_running = False
        if self.sock != None:
            self.sock.close()

    def _send_ping(self, interval):
        while True:
            for _ in range(interval):
                app.APP.monitor.waitForAbort(1)
                if not self.keep_running:
                    return
            self.sock.ping()

    def run_forever(self, sockopt=None, sslopt=None, ping_interval=0):
        """
        run event loop for WebSocket framework.
        This loop is infinite loop and is alive during websocket is available.
        sockopt: values for socket.setsockopt.
            sockopt must be tuple and each element is argument of
            sock.setscokopt.
        sslopt: ssl socket optional dict.
        ping_interval: automatically send "ping" command every specified
            period(second)
            if set to 0, not send automatically.
        """
        if sockopt is None:
            sockopt = []
        if sslopt is None:
            sslopt = {}
        if self.sock:
            raise WebSocketException("socket is already opened")
        thread = None
        self.keep_running = True

        try:
            self.sock = WebSocket(self.get_mask_key,
                                  sockopt=sockopt,
                                  sslopt=sslopt)
            self.sock.settimeout(DEFAULT_TIMEOUT)
            self.sock.connect(self.url, header=self.header)
            self._callback(self.on_open)

            if ping_interval:
                thread = threading.Thread(target=self._send_ping,
                                          args=(ping_interval,))
                thread.setDaemon(True)
                thread.start()

            while self.keep_running:
                try:
                    data = self.sock.recv()
                    if data is None or self.keep_running is False:
                        break
                    self._callback(self.on_message, data)
                except Exception as e:
                    if "timed out" not in e.args[0]:
                        raise e

        except Exception as e:
            self._callback(self.on_error, e)
        finally:
            if thread:
                self.keep_running = False
            self.sock.close()
            self._callback(self.on_close)
            self.sock = None

    def _callback(self, callback, *args):
        if callback:
            try:
                callback(self, *args)
            except Exception as e:
                LOG.error(e)
                _, _, tb = sys.exc_info()
                traceback.print_tb(tb)


if __name__ == "__main__":
    enable_trace(True)
    WEBSOCKET = create_connection("ws://echo.websocket.org/")
    LOG.info("Sending 'Hello, World'...")
    WEBSOCKET.send("Hello, World")
    LOG.info("Sent")
    LOG.info("Receiving...")
    RESULT = WEBSOCKET.recv()
    LOG.info("Received '%s'", RESULT)
    WEBSOCKET.close()
