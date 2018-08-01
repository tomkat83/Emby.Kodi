#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
import httplib
import traceback
import string
import errno
from socket import error as socket_error

###############################################################################

LOG = getLogger('PLEX.httppersist')

###############################################################################


class RequestMgr:
    def __init__(self):
        self.conns = {}

    def getConnection(self, protocol, host, port):
        conn = self.conns.get(protocol + host + str(port), False)
        if not conn:
            if protocol == "https":
                conn = httplib.HTTPSConnection(host, port)
            else:
                conn = httplib.HTTPConnection(host, port)
            self.conns[protocol + host + str(port)] = conn
        return conn

    def closeConnection(self, protocol, host, port):
        conn = self.conns.get(protocol + host + str(port), False)
        if conn:
            conn.close()
            self.conns.pop(protocol + host + str(port), None)

    def dumpConnections(self):
        for conn in self.conns.values():
            conn.close()
        self.conns = {}

    def post(self, host, port, path, body, header={}, protocol="http"):
        conn = None
        try:
            conn = self.getConnection(protocol, host, port)
            header['Connection'] = "keep-alive"
            conn.request("POST", path, body, header)
            data = conn.getresponse()
            if int(data.status) >= 400:
                LOG.error("HTTP response error: %s" % str(data.status))
                # this should return false, but I'm hacking it since iOS
                # returns 404 no matter what
                return data.read() or True
            else:
                return data.read() or True
        except socket_error as serr:
            # Ignore remote close and connection refused (e.g. shutdown PKC)
            if serr.errno in (errno.WSAECONNABORTED, errno.WSAECONNREFUSED):
                pass
            else:
                LOG.error("Unable to connect to %s\nReason:" % host)
                LOG.error(traceback.print_exc())
            self.conns.pop(protocol + host + str(port), None)
            if conn:
                conn.close()
            return False
        except Exception as e:
            LOG.error("Exception encountered: %s", e)
            # Close connection just in case
            try:
                conn.close()
            except:
                pass
            return False

    def getwithparams(self, host, port, path, params, header={},
                      protocol="http"):
        newpath = path + '?'
        pairs = []
        for key in params:
            pairs.append(str(key) + '=' + str(params[key]))
        newpath += string.join(pairs, '&')
        return self.get(host, port, newpath, header, protocol)

    def get(self, host, port, path, header={}, protocol="http"):
        try:
            conn = self.getConnection(protocol, host, port)
            header['Connection'] = "keep-alive"
            conn.request("GET", path, headers=header)
            data = conn.getresponse()
            if int(data.status) >= 400:
                LOG.error("HTTP response error: %s", str(data.status))
                return False
            else:
                return data.read() or True
        except socket_error as serr:
            # Ignore remote close and connection refused (e.g. shutdown PKC)
            if serr.errno in (errno.WSAECONNABORTED, errno.WSAECONNREFUSED):
                pass
            else:
                LOG.error("Unable to connect to %s\nReason:", host)
                LOG.error(traceback.print_exc())
            self.conns.pop(protocol + host + str(port), None)
            conn.close()
            return False
