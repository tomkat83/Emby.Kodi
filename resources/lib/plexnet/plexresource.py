from xml.etree import ElementTree

import http
import exceptions
import plexobjects
import plexconnection
import util

RESOURCES = 'https://plex.tv/api/resources?includeHttps=1'


class PlexResource(object):
    def __init__(self, data):
        self.connection = None
        self.connections = []
        self.accessToken = None
        self.sourceType = None

        if data is None:
            return

        self.accessToken = data.attrib.get('accessToken')
        self.httpsRequired = data.attrib.get('httpsRequired') == '1'
        self.type = data.attrib.get('type')
        self.clientIdentifier = data.attrib.get('clientIdentifier')
        self.product = data.attrib.get('product')
        self.provides = data.attrib.get('provides')
        self.serverClass = data.attrib.get('serverClass')
        self.sourceType = data.attrib.get('sourceType')
        self.uuid = self.clientIdentifier

        hasSecureConn = False

        for conn in data.findall('Connection'):
            if conn.attrib.get('protocol') == "https":
                hasSecureConn = True
                break

        for conn in data.findall('Connection'):
            connection = plexconnection.PlexConnection(
                plexconnection.PlexConnection.SOURCE_MYPLEX,
                conn.attrib.get('uri'),
                conn.attrib.get('local') == '1',
                self.accessToken,
                hasSecureConn and conn.attrib.get('protocol') != "https"
            )

            # Keep the secure connection on top
            if connection.isSecure:
                self.connections.insert(0, connection)
            else:
                self.connections.append(connection)

            # If the connection is one of our plex.direct secure connections, add
            # the nonsecure variant as well, unless https is required.
            #
            if self.httpsRequired and conn.attrib.get('protocol') == "https" and conn.attrib.get('address') not in conn.attrib.get('uri'):
                self.connections.append(
                    plexconnection.PlexConnection(
                        plexconnection.PlexConnection.SOURCE_MYPLEX,
                        "http://{0}:{1}".format(conn.attrib.get('address'), conn.attrib.get('port')),
                        conn.attrib.get('local') == '1',
                        self.accessToken,
                        True
                    )
                )

    def __repr__(self):
        return '<{0}:{1}>'.format(self.__class__.__name__, self.name.encode('utf8'))


class ResourceConnection(plexobjects.PlexObject):
    # Constants
    STATE_UNKNOWN = "unknown"
    STATE_UNREACHABLE = "unreachable"
    STATE_REACHABLE = "reachable"
    STATE_UNAUTHORIZED = "unauthorized"
    STATE_INSECURE = "insecure_untested"

    SOURCE_MANUAL = 1
    SOURCE_DISCOVERED = 2
    SOURCE_MYPLEX = 4

    SCORE_REACHABLE = 4
    SCORE_LOCAL = 2
    SCORE_SECURE = 1

    def init(self, data):
        self.secure = True
        self.reachable = False
        self.data = None

    def __repr__(self):
        return '<{0}:{1}>'.format(self.__class__.__name__, self.uri.encode('utf8'))

    @property
    def http_uri(self):
        return 'http://{0}:{1}'.format(self.address, self.port)

    @property
    def URL(self):
        if self.secure:
            return self.uri
        else:
            return self.http_url

    def connect(self):
        util.LOG('Connecting: {0}'.format(util.cleanToken(self.URL)))
        try:
            self.data = self.query('/')
            self.reachable = True
            return True
        except Exception as err:
            util.ERROR(util.cleanToken(self.URL), err)

        util.LOG('Connecting: Secure failed, trying insecure...')
        self.secure = False

        try:
            self.data = self.query('/')
            self.reachable = True
            return True
        except Exception as err:
            util.ERROR(util.cleanToken(self.URL), err)

        return False

    def headers(self, token=None):
        headers = util.BASE_HEADERS.copy()
        if token:
            headers['X-Plex-Token'] = token
        return headers

    def query(self, path, method=None, token=None, **kwargs):
        method = method or http.requests.get
        url = self.getURL(path)
        util.LOG('{0} {1}'.format(method.__name__.upper(), url))
        response = method(url, headers=self.headers(token), timeout=util.TIMEOUT, **kwargs)
        if response.status_code not in (200, 201):
            codename = http.status_codes.get(response.status_code)[0]
            raise exceptions.BadRequest('({0}) {1}'.format(response.status_code, codename))
        data = response.text.encode('utf8')

        return ElementTree.fromstring(data) if data else None

    def getURL(self, path, token=None):
        if token:
            delim = '&' if '?' in path else '?'
            return '{base}{path}{delim}X-Plex-Token={token}'.format(base=self.URL, path=path, delim=delim, token=util.hideToken(token))
        return '{0}{1}'.format(self.URL, path)


class PlexResourceList(plexobjects.PlexItemList):
    def __init__(self, data, initpath=None, server=None):
        self._data = data
        self.initpath = initpath
        self._server = server
        self._items = None

    @property
    def items(self):
        if self._items is None:
            if self._data is not None:
                self._items = [PlexResource(elem, initpath=self.initpath, server=self._server) for elem in self._data]
            else:
                self._items = []

        return self._items


def fetchResources(token):
    headers = util.BASE_HEADERS.copy()
    headers['X-Plex-Token'] = token
    util.LOG('GET {0}?X-Plex-Token={1}'.format(RESOURCES, util.hideToken(token)))
    response = http.GET(RESOURCES)
    data = ElementTree.fromstring(response.text.encode('utf8'))
    import plexserver
    return [plexserver.PlexServer(elem) for elem in data]


def findResource(resources, search, port=32400):
    """ Searches server.name """
    search = search.lower()
    util.LOG('Looking for server: {0}'.format(search))
    for server in resources:
        if search == server.name.lower():
            util.LOG('Server found: {0}'.format(server))
            return server
    util.LOG('Unable to find server: {0}'.format(search))
    raise exceptions.NotFound('Unable to find server: {0}'.format(search))


def findResourceByID(resources, ID):
    """ Searches server.clientIdentifier """
    util.LOG('Looking for server by ID: {0}'.format(ID))
    for server in resources:
        if ID == server.clientIdentifier:
            util.LOG('Server found by ID: {0}'.format(server))
            return server
    util.LOG('Unable to find server by ID: {0}'.format(ID))
    raise exceptions.NotFound('Unable to find server by ID: {0}'.format(ID))
