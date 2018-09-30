import http
import plexobjects


class PlexResult(http.HttpResponse):
    def __init__(self, server, address):
        self.server = server
        self.address = address
        self.container = None
        self.parsed = None
        self.items = []

    def setResponse(self, event):
        self.event = event

    def parseResponse(self):
        if self.parsed:
            return self.parsed

        self.parsed = False

        if self.isSuccess():
            data = self.getBodyXml()
            if data is not None:
                self.container = plexobjects.PlexContainer(data, initpath=self.address, server=self.server, address=self.address)

                for node in data:
                    self.addItem(self.container, node)

                self.parsed = True

        return self.parsed

    def parseFakeXMLResponse(self, data):
        if self.parsed:
            return self.parsed

        self.parsed = False

        if data is not None:
            self.container = plexobjects.PlexContainer(data, initpath=self.address, server=self.server, address=self.address)

            for node in data:
                self.addItem(self.container, node)

            self.parsed = True

        return self.parsed

    def addItem(self, container, node):
        if node.attrib.get('type') in ('track', 'movie', 'episode', 'photo') and node.tag != 'PlayQueue':
            item = plexobjects.buildItem(self.server, node, self.address, container=self.container)
        else:
            item = plexobjects.PlexObject(node, server=self.container.server, container=self.container)

        # TODO(rob): handle channel settings. We should be able to utilize
        # the settings component with some modifications.
        if not item.isSettings():
            self.items.append(item)
        else:
            # Decrement the size and total size if applicable
            if self.container.get("size"):
                self.container.size = plexobjects.PlexValue(str(self.container.size.asInt() - 1))
            if self.container.get("totalSize"):
                self.container.totalSize = plexobjects.PlexValue(str(self.container.totalSize.asInt() - 1))


class PlexServerResult(PlexResult):
    def parseResponse(self):
        if self.parsed:
            return self.parsed

        self.parsed = False

        if self.isSuccess():
            data = self.getBodyXml()
            if data is not None:
                self.container = plexobjects.PlexServerContainer(data, initpath=self.address, server=self.server, address=self.address)

                for node in data:
                    self.addItem(self.container, node)

                self.parsed = True

        return self.parsed

    def parseFakeXMLResponse(self, data):
        if self.parsed:
            return self.parsed

        self.parsed = False

        if data is not None:
            self.container = plexobjects.PlexServerContainer(data, initpath=self.address, server=self.server, address=self.address)

            for node in data:
                self.addItem(self.container, node)

            self.parsed = True

        return self.parsed
