#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger

from ..utils import cast, to_list

LOG = getLogger('PLEX.' + __name__)


class Connection(object):
    def __init__(self, xml=None, **kwargs):
        self.protocol = None
        self.address = None
        self.port = None
        self.uri = None
        self.local = None
        if xml:
            self.load_from_xml(xml)
        # Set all remaining attributes set on Class instantiation
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __unicode__(self):
        return '<Connection {self.uri}>'.format(self=self)

    def __repr__(self):
        return self.__unicode__().encode('utf-8')

    def __eq__(self, other):
        return self.uri == other.uri

    def __ne__(self, other):
        return self.uri != other.uri

    def load_from_xml(self, xml):
        """
        Throw in an etree xml-element to load PMS settings from it
        """
        if xml.tag != 'Connection':
            raise RuntimeError('Did not receive Connection xml but %s'
                               % xml.tag)
        self.protocol = cast(unicode, xml.get('protocol'))
        self.address = cast(unicode, xml.get('address'))
        self.port = cast(int, xml.get('port'))
        self.uri = cast(unicode, xml.get('uri'))
        self.local = cast(bool, xml.get('local'))


class PlexServer(object):
    def __init__(self, xml=None, **kwargs):
        # Information from plex.tv
        self.name = None
        self.clientIdentifier = None
        self.provides = set()
        self.owned = None
        self.home = None
        self.httpsRequired = None
        self.synced = None
        self.relay = None
        self.publicAddressMatches = None
        self.presence = None
        self.accessToken = None

        self.product = None  # Usually "Plex Media Server"
        self.ownerId = None  # User id of the owner of this PMS
        self.owner = None  # User name of the (foreign!) owner
        self.productVersion = None
        self.platform = None
        self.platformVersion = None
        self.device = None
        self.createdAt = None
        self.lastSeenAt = None

        # Connection info
        self.connections = []
        if xml:
            self.load_from_xml(xml)
        # Set all remaining attributes set on Class instantiation
        for key, value in kwargs.items():
            setattr(self, key, value)

    def load_from_xml(self, xml):
        """
        Throw in an etree xml-element to load PMS settings from it
        """
        if xml.tag != 'Device':
            raise RuntimeError('Did not receive Device xml but %s' % xml.tag)
        self.name = cast(unicode, xml.get('name'))
        self.clientIdentifier = cast(unicode, xml.get('clientIdentifier'))
        self.provides = set(to_list(cast(unicode, xml.get('provides'))))
        self.owned = cast(bool, xml.get('owned'))
        self.home = cast(bool, xml.get('home'))
        self.httpsRequired = cast(bool, xml.get('httpsRequired'))
        self.synced = cast(bool, xml.get('synced'))
        self.relay = cast(bool, xml.get('relay'))
        self.publicAddressMatches = cast(bool,
                                         xml.get('publicAddressMatches'))
        self.presence = cast(bool, xml.get('presence'))
        self.accessToken = cast(unicode, xml.get('accessToken'))
        self.product = cast(unicode, xml.get('product'))
        self.ownerId = cast(int, xml.get('ownerId'))
        self.owner = cast(unicode, xml.get('sourceTitle'))
        self.productVersion = cast(unicode, xml.get('productVersion'))
        self.platform = cast(unicode, xml.get('platform'))
        self.platformVersion = cast(unicode, xml.get('platformVersion'))
        self.device = cast(unicode, xml.get('device'))
        self.createdAt = cast(int, xml.get('createdAt'))
        self.lastSeenAt = cast(int, xml.get('lastSeenAt'))

        for connection in xml.findall('Connection'):
            self.connections.append(Connection(xml=connection))

    def __unicode__(self):
        return '<PlexServer {self.name}:{self.clientIdentifier}>'.format(self=self)

    def __repr__(self):
        return self.__unicode__().encode('utf-8')

    def __eq__(self, other):
        return self.clientIdentifier == other.clientIdentifier

    def __ne__(self, other):
        return self.clientIdentifier != other.clientIdentifier
