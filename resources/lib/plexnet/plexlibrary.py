# -*- coding: utf-8 -*-
"""
PlexLibrary
"""
import plexobjects
import playlist
import media
import exceptions
import util
import signalsmixin


class Library(plexobjects.PlexObject):
    def __repr__(self):
        return '<Library:{0}>'.format(self.title1.encode('utf8'))

    def sections(self):
        items = []

        path = '/library/sections'
        for elem in self.server.query(path):
            stype = elem.attrib['type']
            if stype in SECTION_TYPES:
                cls = SECTION_TYPES[stype]
                items.append(cls(elem, initpath=path, server=self.server, container=self))
        return items

    def section(self, title=None):
        for item in self.sections():
            if item.title == title:
                return item
        raise exceptions.NotFound('Invalid library section: %s' % title)

    def all(self):
        return plexobjects.listItems(self.server, '/library/all')

    def onDeck(self):
        return plexobjects.listItems(self.server, '/library/onDeck')

    def recentlyAdded(self):
        return plexobjects.listItems(self.server, '/library/recentlyAdded')

    def get(self, title):
        return plexobjects.findItem(self.server, '/library/all', title)

    def getByKey(self, key):
        return plexobjects.findKey(self.server, key)

    def search(self, title, libtype=None, **kwargs):
        """ Searching within a library section is much more powerful. It seems certain attributes on the media
            objects can be targeted to filter this search down a bit, but I havent found the documentation for
            it. For example: "studio=Comedy%20Central" or "year=1999" "title=Kung Fu" all work. Other items
            such as actor=<id> seem to work, but require you already know the id of the actor.
            TLDR: This is untested but seems to work. Use library section search when you can.
        """
        args = {}
        if title:
            args['title'] = title
        if libtype:
            args['type'] = plexobjects.searchType(libtype)
        for attr, value in kwargs.items():
            args[attr] = value
        query = '/library/all%s' % util.joinArgs(args)
        return plexobjects.listItems(self.server, query)

    def cleanBundles(self):
        self.server.query('/library/clean/bundles')

    def emptyTrash(self):
        for section in self.sections():
            section.emptyTrash()

    def optimize(self):
        self.server.query('/library/optimize')

    def refresh(self):
        self.server.query('/library/sections/all/refresh')


class LibrarySection(plexobjects.PlexObject):
    ALLOWED_FILTERS = ()
    ALLOWED_SORT = ()
    BOOLEAN_FILTERS = ('unwatched', 'duplicate')

    isLibraryPQ = True

    def __repr__(self):
        title = self.title.replace(' ', '.')[0:20]
        return '<%s:%s>' % (self.__class__.__name__, title.encode('utf8'))

    @staticmethod
    def fromFilter(filter_):
        cls = SECTION_IDS.get(filter_.getLibrarySectionType())
        if not cls:
            return
        section = cls(None, initpath=filter_.initpath, server=filter_.server, container=filter_.container)
        section.key = filter_.getLibrarySectionId()
        section.title = filter_.reasonTitle
        section.type = cls.TYPE
        return section

    def reload(self, **kwargs):
        """ Reload the data for this object from PlexServer XML. """
        initpath = '/library/sections/{0}'.format(self.key)
        key = self.key
        try:
            data = self.server.query(initpath, params=kwargs)
        except Exception, e:
            import traceback
            traceback.print_exc()
            util.ERROR(err=e)
            self.initpath = self.key
            return

        self._setData(data[0])
        self.initpath = self.key = key

    def isDirectory(self):
        return True

    def isLibraryItem(self):
        return True

    def getAbsolutePath(self, key):
        if key == 'key':
            return '/library/sections/{0}/all'.format(self.key)

        return plexobjects.PlexObject.getAbsolutePath(self, key)

    def all(self, start=None, size=None, filter_=None, sort=None, unwatched=False, type_=None):
        if self.key.startswith('/'):
            path = '{0}/all'.format(self.key)
        else:
            path = '/library/sections/{0}/all'.format(self.key)

        args = {}

        if size is not None:
            args['X-Plex-Container-Start'] = start
            args['X-Plex-Container-Size'] = size

        if filter_:
            args[filter_[0]] = filter_[1]

        if sort:
            args['sort'] = '{0}:{1}'.format(*sort)

        if type_:
            args['type'] = str(type_)

        if unwatched:
            args[self.TYPE == 'movie' and 'unwatched' or 'unwatchedLeaves'] = 1

        if args:
            path += util.joinArgs(args)

        return plexobjects.listItems(self.server, path)

    def jumpList(self, filter_=None, sort=None, unwatched=False, type_=None):
        if self.key.startswith('/'):
            path = '{0}/firstCharacter'.format(self.key)
        else:
            path = '/library/sections/{0}/firstCharacter'.format(self.key)

        args = {}

        if filter_:
            args[filter_[0]] = filter_[1]

        if sort:
            args['sort'] = '{0}:{1}'.format(*sort)

        if type_:
            args['type'] = str(type_)

        if unwatched:
            args[self.TYPE == 'movie' and 'unwatched' or 'unwatchedLeaves'] = 1

        if args:
            path += util.joinArgs(args)

        try:
            return plexobjects.listItems(self.server, path, bytag=True)
        except exceptions.BadRequest:
            util.ERROR('jumpList() request error for path: {0}'.format(repr(path)))
            return None

    @property
    def onDeck(self):
        return plexobjects.listItems(self.server, '/library/sections/%s/onDeck' % self.key)

    def analyze(self):
        self.server.query('/library/sections/%s/analyze' % self.key)

    def emptyTrash(self):
        self.server.query('/library/sections/%s/emptyTrash' % self.key)

    def refresh(self):
        self.server.query('/library/sections/%s/refresh' % self.key)

    def listChoices(self, category, libtype=None, **kwargs):
        """ List choices for the specified filter category. kwargs can be any of the same
            kwargs in self.search() to help narrow down the choices to only those that
            matter in your current context.
        """
        if category in kwargs:
            raise exceptions.BadRequest('Cannot include kwarg equal to specified category: %s' % category)
        args = {}
        for subcategory, value in kwargs.items():
            args[category] = self._cleanSearchFilter(subcategory, value)
        if libtype is not None:
            args['type'] = plexobjects.searchType(libtype)
        query = '/library/sections/%s/%s%s' % (self.key, category, util.joinArgs(args))

        return plexobjects.listItems(self.server, query, bytag=True)

    def search(self, title=None, sort=None, maxresults=999999, libtype=None, **kwargs):
        """ Search the library. If there are many results, they will be fetched from the server
            in batches of X_PLEX_CONTAINER_SIZE amounts. If you're only looking for the first <num>
            results, it would be wise to set the maxresults option to that amount so this functions
            doesn't iterate over all results on the server.
            title: General string query to search for.
            sort: column:dir; column can be any of {addedAt, originallyAvailableAt, lastViewedAt,
              titleSort, rating, mediaHeight, duration}. dir can be asc or desc.
            maxresults: Only return the specified number of results
            libtype: Filter results to a spcifiec libtype {movie, show, episode, artist, album, track}
            kwargs: Any of the available filters for the current library section. Partial string
              matches allowed. Multiple matches OR together. All inputs will be compared with the
              available options and a warning logged if the option does not appear valid.
                'unwatched': Display or hide unwatched content (True, False). [all]
                'duplicate': Display or hide duplicate items (True, False). [movie]
                'actor': List of actors to search ([actor_or_id, ...]). [movie]
                'collection': List of collections to search within ([collection_or_id, ...]). [all]
                'contentRating': List of content ratings to search within ([rating_or_key, ...]). [movie, tv]
                'country': List of countries to search within ([country_or_key, ...]). [movie, music]
                'decade': List of decades to search within ([yyy0, ...]). [movie]
                'director': List of directors to search ([director_or_id, ...]). [movie]
                'genre': List Genres to search within ([genere_or_id, ...]). [all]
                'network': List of TV networks to search within ([resolution_or_key, ...]). [tv]
                'resolution': List of video resolutions to search within ([resolution_or_key, ...]). [movie]
                'studio': List of studios to search within ([studio_or_key, ...]). [music]
                'year': List of years to search within ([yyyy, ...]). [all]
        """
        # Cleanup the core arguments
        args = {}
        for category, value in kwargs.items():
            args[category] = self._cleanSearchFilter(category, value, libtype)
        if title is not None:
            args['title'] = title
        if sort is not None:
            args['sort'] = self._cleanSearchSort(sort)
        if libtype is not None:
            args['type'] = plexobjects.searchType(libtype)
        # Iterate over the results
        results, subresults = [], '_init'
        args['X-Plex-Container-Start'] = 0
        args['X-Plex-Container-Size'] = min(util.X_PLEX_CONTAINER_SIZE, maxresults)
        while subresults and maxresults > len(results):
            query = '/library/sections/%s/all%s' % (self.key, util.joinArgs(args))
            subresults = plexobjects.listItems(self.server, query)
            results += subresults[:maxresults - len(results)]
            args['X-Plex-Container-Start'] += args['X-Plex-Container-Size']
        return results

    def _cleanSearchFilter(self, category, value, libtype=None):
        # check a few things before we begin
        if category not in self.ALLOWED_FILTERS:
            raise exceptions.BadRequest('Unknown filter category: %s' % category)
        if category in self.BOOLEAN_FILTERS:
            return '1' if value else '0'
        if not isinstance(value, (list, tuple)):
            value = [value]
        # convert list of values to list of keys or ids
        result = set()
        choices = self.listChoices(category, libtype)
        lookup = {}
        for c in choices:
            lookup[c.title.lower()] = c.key

        allowed = set(c.key for c in choices)
        for item in value:
            item = str(item.id if isinstance(item, media.MediaTag) else item).lower()
            # find most logical choice(s) to use in url
            if item in allowed:
                result.add(item)
                continue
            if item in lookup:
                result.add(lookup[item])
                continue
            matches = [k for t, k in lookup.items() if item in t]
            if matches:
                map(result.add, matches)
                continue
            # nothing matched; use raw item value
            util.LOG('Filter value not listed, using raw item value: {0}'.format(item))
            result.add(item)
        return ','.join(result)

    def _cleanSearchSort(self, sort):
        sort = '%s:asc' % sort if ':' not in sort else sort
        scol, sdir = sort.lower().split(':')
        lookup = {}
        for s in self.ALLOWED_SORT:
            lookup[s.lower()] = s
        if scol not in lookup:
            raise exceptions.BadRequest('Unknown sort column: %s' % scol)
        if sdir not in ('asc', 'desc'):
            raise exceptions.BadRequest('Unknown sort dir: %s' % sdir)
        return '%s:%s' % (lookup[scol], sdir)


class MovieSection(LibrarySection):
    ALLOWED_FILTERS = (
        'unwatched', 'duplicate', 'year', 'decade', 'genre', 'contentRating', 'collection',
        'director', 'actor', 'country', 'studio', 'resolution'
    )
    ALLOWED_SORT = (
        'addedAt', 'originallyAvailableAt', 'lastViewedAt', 'titleSort', 'rating',
        'mediaHeight', 'duration'
    )
    TYPE = 'movie'
    ID = '1'


class ShowSection(LibrarySection):
    ALLOWED_FILTERS = ('unwatched', 'year', 'genre', 'contentRating', 'network', 'collection')
    ALLOWED_SORT = ('addedAt', 'lastViewedAt', 'originallyAvailableAt', 'titleSort', 'rating', 'unwatched')
    TYPE = 'show'
    ID = '2'

    def searchShows(self, **kwargs):
        return self.search(libtype='show', **kwargs)

    def searchEpisodes(self, **kwargs):
        return self.search(libtype='episode', **kwargs)


class MusicSection(LibrarySection):
    ALLOWED_FILTERS = ('genre', 'country', 'collection')
    ALLOWED_SORT = ('addedAt', 'lastViewedAt', 'viewCount', 'titleSort')
    TYPE = 'artist'
    ID = '8'

    def searchShows(self, **kwargs):
        return self.search(libtype='artist', **kwargs)

    def searchEpisodes(self, **kwargs):
        return self.search(libtype='album', **kwargs)

    def searchTracks(self, **kwargs):
        return self.search(libtype='track', **kwargs)


class PhotoSection(LibrarySection):
    ALLOWED_FILTERS = ()
    ALLOWED_SORT = ('addedAt', 'lastViewedAt', 'viewCount', 'titleSort')
    TYPE = 'photo'
    ID = 'None'

    def isPhotoOrDirectoryItem(self):
        return True


@plexobjects.registerLibType
class Generic(plexobjects.PlexObject):
    TYPE = 'Directory'

    def __repr__(self):
        title = self.title.replace(' ', '.')[0:20]
        return '<{0}:{1}:{2}>'.format(self.__class__.__name__, self.key, title)


@plexobjects.registerLibType
class Playlist(playlist.BasePlaylist, signalsmixin.SignalsMixin):
    TYPE = 'playlist'

    def __init__(self, *args, **kwargs):
        playlist.BasePlaylist.__init__(self, *args, **kwargs)
        self._itemsLoaded = False

    def __repr__(self):
        title = self.title.replace(' ', '.')[0:20]
        return '<{0}:{1}:{2}>'.format(self.__class__.__name__, self.key, title)

    def exists(self):
        try:
            self.server.query('/playlists/{0}'.format(self.ratingKey))
            return True
        except exceptions.BadRequest:
            return False

    def isMusicOrDirectoryItem(self):
        return self.playlistType == 'audio'

    def isVideoOrDirectoryItem(self):
        return self.playlistType == 'video'

    def items(self):
        if not self._itemsLoaded:
            path = '/playlists/{0}/items'.format(self.ratingKey)
            self._items = plexobjects.listItems(self.server, path)
            self._itemsLoaded = True

        return playlist.BasePlaylist.items(self)

    def extend(self, start=0, size=0):
        if not self._items:
            self._items = [None] * self.leafCount.asInt()

        args = {}

        if size is not None:
            args['X-Plex-Container-Start'] = start
            args['X-Plex-Container-Size'] = size

        path = '/playlists/{0}/items'.format(self.ratingKey)
        if args:
            path += util.joinArgs(args) if '?' not in path else '&' + util.joinArgs(args).lstrip('?')

        items = plexobjects.listItems(self.server, path)
        self._items[start:start + len(items)] = items

        self.trigger('items.added')

        return items

    def unshuffledItems(self):
        if not self._itemsLoaded:
            self.items()
        return self._items

    @property
    def defaultThumb(self):
        return self.composite

    def buildComposite(self, **kwargs):
        if kwargs:
            params = '?' + '&'.join('{0}={1}'.format(k, v) for k, v in kwargs.items())
        else:
            params = ''

        path = self.composite + params
        return self.getServer().buildUrl(path, True)


class BaseHub(plexobjects.PlexObject):
    def reset(self):
        self.set('offset', 0)
        self.set('size', len(self.items))
        totalSize = self.items[0].container.totalSize.asInt()
        if totalSize:  # Hubs from a list of hubs don't have this, so it it's not here this is intital and we can leave as is
            self.set(
                'more',
                (self.items[0].container.offset.asInt() + self.items[0].container.size.asInt() < totalSize) and '1' or ''
            )


class Hub(BaseHub):
    TYPE = "Hub"

    def init(self, data):
        self.items = []

        container = plexobjects.PlexContainer(data, self.key, self.server, self.key or '')

        if self.type == 'genre':
            self.items = [media.Genre(elem, initpath='/hubs', server=self.server, container=container) for elem in data]
        elif self.type == 'director':
            self.items = [media.Director(elem, initpath='/hubs', server=self.server, container=container) for elem in data]
        elif self.type == 'actor':
            self.items = [media.Role(elem, initpath='/hubs', server=self.server, container=container) for elem in data]
        else:
            for elem in data:
                try:
                    self.items.append(plexobjects.buildItem(self.server, elem, '/hubs', container=container, tag_fallback=True))
                except exceptions.UnknownType:
                    util.DEBUG_LOG('Unkown hub item type({1}): {0}'.format(elem, elem.attrib.get('type')))

    def __repr__(self):
        return '<{0}:{1}>'.format(self.__class__.__name__, self.hubIdentifier)

    def reload(self, **kwargs):
        """ Reload the data for this object from PlexServer XML. """
        try:
            data = self.server.query(self.key, params=kwargs)
        except Exception, e:
            import traceback
            traceback.print_exc()
            util.ERROR(err=e)
            self.initpath = self.key
            return

        self.initpath = self.key
        self._setData(data)
        self.init(data)

    def extend(self, start=None, size=None):
        path = self.key

        args = {}

        if size is not None:
            args['X-Plex-Container-Start'] = start
            args['X-Plex-Container-Size'] = size

        if args:
            path += util.joinArgs(args) if '?' not in path else '&' + util.joinArgs(args).lstrip('?')

        items = plexobjects.listItems(self.server, path)
        self.offset = plexobjects.PlexValue(start)
        self.size = plexobjects.PlexValue(len(items))
        self.more = plexobjects.PlexValue(
            (items[0].container.offset.asInt() + items[0].container.size.asInt() < items[0].container.totalSize.asInt()) and '1' or ''
        )
        return items


class PlaylistHub(BaseHub):
    TYPE = "Hub"
    type = None
    hubIdentifier = None

    def init(self, data):
        try:
            self.items = self.extend(0, 10)
        except exceptions.BadRequest:
            util.DEBUG_LOG('AudioPlaylistHub: Bad request: {0}'.format(self))
            self.items = []

    def extend(self, start=None, size=None):
        path = '/playlists/all?playlistType={0}'.format(self.type)

        args = {}

        if size is not None:
            args['X-Plex-Container-Start'] = start
            args['X-Plex-Container-Size'] = size
        else:
            start = 0

        if args:
            path += '&' + util.joinArgs(args).lstrip('?')

        items = plexobjects.listItems(self.server, path)

        if not items:
            return

        self.set('offset', start)
        self.set('size', len(items))
        self.set('more', (items[0].container.offset.asInt() + items[0].container.size.asInt() < items[0].container.totalSize.asInt()) and '1' or '')
        return items


class AudioPlaylistHub(PlaylistHub):
    type = 'audio'
    hubIdentifier = 'playlists.audio'


class VideoPlaylistHub(PlaylistHub):
    type = 'video'
    hubIdentifier = 'playlists.video'


SECTION_TYPES = {
    MovieSection.TYPE: MovieSection,
    ShowSection.TYPE: ShowSection,
    MusicSection.TYPE: MusicSection,
    PhotoSection.TYPE: PhotoSection
}

SECTION_IDS = {
    MovieSection.ID: MovieSection,
    ShowSection.ID: ShowSection,
    MusicSection.ID: MusicSection,
    PhotoSection.ID: PhotoSection
}
