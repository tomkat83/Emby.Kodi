#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
from re import sub

import xbmcgui

from ..utils import cast
from ..plex_db import PlexDB
from .. import utils, timing, variables as v, app, plex_functions as PF
from .. import widgets

LOG = getLogger('PLEX.api')

METADATA_PROVIDERS = (('imdb', utils.REGEX_IMDB),
                      ('tvdb', utils.REGEX_TVDB),
                      ('tmdb', utils.REGEX_TMDB),
                      ('anidb', utils.REGEX_ANIDB))


class Base(object):
    """
    Processes a Plex media server's XML response

    xml: xml.etree.ElementTree element
    """

    def __init__(self, xml):
        self.xml = xml
        # which media part in the XML response shall we look at if several
        # media files are present for the SAME video? (e.g. a 4k and a 1080p
        # version)
        self.part = 0
        self.mediastream = None
        # Make sure we're only checking our Plex DB once
        self._checked_db = False
        # In order to run through the leaves of the xml only once
        self._scanned_children = False
        self._genres = []
        self._countries = []
        self._collections = []
        self._people = []
        self._cast = []
        self._directors = []
        self._writers = []
        self._producers = []
        self._locations = []
        self._markers = []
        self._labels = []
        self._guids = {}
        self._coll_match = None
        # Plex DB attributes
        self._section_id = None
        self._kodi_id = None
        self._last_sync = None
        self._last_checksum = None
        self._kodi_fileid = None
        self._kodi_pathid = None
        self._fanart_synced = None

    @property
    def tag(self):
        """
        Returns the xml etree tag, e.g. 'Directory', 'Playlist', 'Hub', 'Video'
        """
        return self.xml.tag

    def tag_label(self):
        """
        Returns the 'tag' attribute of the xml
        """
        return self.xml.get('tag')

    @property
    def attrib(self):
        """
        Returns the xml etree attrib dict
        """
        return self.xml.attrib

    @property
    def plex_id(self):
        """
        Returns the Plex ratingKey as an integer or None
        """
        return cast(int, self.xml.get('ratingKey'))

    @property
    def plex_guid(self):
        """
        Returns the Plex guid as unicode or None. Note that you can get
        SEVERAL plex_ids per Plex guid as you have unique Plex id's per
        edition (e.g. director's cut, normal cut, ...) but potentially
        only a single guid per "movie" encompassing all editions
        """
        return self.xml.get('guid')

    @property
    def fast_key(self):
        """
        Returns the 'fastKey' as unicode or None
        """
        return self.xml.get('fastKey')

    @property
    def plex_type(self):
        """
        Returns the type of media, e.g. 'movie' or 'clip' for trailers as
        Unicode or None.
        """
        return self.xml.get('type')

    @property
    def subtype(self):
        """
        Returns the subtype of media, e.g. 'clip' as string or None.
        """
        return self.xml.get('subtype')

    @property
    def section_id(self):
        self.check_db()
        return self._section_id

    @property
    def kodi_id(self):
        self.check_db()
        return self._kodi_id

    @property
    def kodi_type(self):
        return v.KODITYPE_FROM_PLEXTYPE[self.plex_type]

    @property
    def last_sync(self):
        self.check_db()
        return self._last_sync

    @property
    def last_checksum(self):
        self.check_db()
        return self._last_checksum

    @property
    def kodi_fileid(self):
        self.check_db()
        return self._kodi_fileid

    @property
    def kodi_pathid(self):
        self.check_db()
        return self._kodi_pathid

    @property
    def fanart_synced(self):
        self.check_db()
        return self._fanart_synced

    @property
    def guids(self):
        self._scan_children()
        return self._guids

    def check_db(self, plexdb=None):
        """
        Check's whether we synched this item to Kodi. If so, then retrieve the
        appropriate Kodi info like the kodi_id and kodi_fileid

        Pass in a plexdb DB-connection for a faster lookup
        """
        if self._checked_db:
            return
        self._checked_db = True
        if self.plex_type == v.PLEX_TYPE_CLIP:
            # Clips won't ever be synched to Kodi
            return
        if plexdb:
            db_item = plexdb.item_by_id(self.plex_id, self.plex_type)
        else:
            with PlexDB(lock=False) as plexdb:
                db_item = plexdb.item_by_id(self.plex_id, self.plex_type)
        if not db_item:
            return
        self._section_id = db_item['section_id']
        self._kodi_id = db_item['kodi_id']
        self._last_sync = db_item['last_sync']
        self._last_checksum = db_item['checksum']
        if 'kodi_fileid' in db_item:
            self._kodi_fileid = db_item['kodi_fileid']
        if 'kodi_pathid' in db_item:
            self._kodi_pathid = db_item['kodi_pathid']
        if 'fanart_synced' in db_item:
            self._fanart_synced = db_item['fanart_synced']

    def check_by_guid(self, plexdb=None):
        """
        Returns a list of db_items synced to Kodi by using the Plex guid or an
        empty list. There can be several items matching a single guid, e.g.
        movie editions.
        """
        if self.plex_guid is None:
            return list()
        if plexdb:
            db_items = plexdb.items_by_guid(self.plex_guid, self.plex_type)
        else:
            with PlexDB(lock=False) as plexdb:
                db_items = plexdb.items_by_guid(self.plex_guid, self.plex_type)
        return db_items

    def path_and_plex_id(self):
        """
        Returns the Plex key such as '/library/metadata/246922' or None
        """
        return self.xml.get('key')

    def item_id(self):
        """
        Returns current playQueueItemID or if unsuccessful the playListItemID
        as int.
        If not found, None is returned
        """
        return (cast(int, self.xml.get('playQueueItemID')) or
                cast(int, self.xml.get('playListItemID')))

    def playlist_type(self):
        """
        Returns the playlist type ('video', 'audio') or None
        """
        return self.xml.get('playlistType')

    def library_section_id(self):
        """
        Returns the id of the Plex library section (for e.g. a movies section)
        as an int or None
        """
        return cast(int, self.xml.get('librarySectionID'))

    def guid_html_escaped(self):
        """
        Returns the 'guid' attribute, e.g.
            'com.plexapp.agents.thetvdb://76648/2/4?lang=en'
        as an HTML-escaped string or None
        """
        guid = self.xml.get('guid')
        return utils.escape_html(guid) if guid else None

    def date_created(self):
        """
        Returns the date when this library item was created in Kodi-time as
        unicode

        If not found, returns 2000-01-01 10:00:00
        """
        res = self.xml.get('addedAt')
        return timing.plex_date_to_kodi(res) if res else '2000-01-01 10:00:00'

    def updated_at(self):
        """
        Returns the last time this item was updated as an int, e.g.
        1524739868 or None
        """
        return cast(int, self.xml.get('updatedAt'))

    def checksum(self):
        """
        Returns the unique int <ratingKey><updatedAt>. If updatedAt is not set,
        addedAt is used.
        """
        return int('%s%s' % (self.xml.get('ratingKey'),
                             abs(int(self.xml.get('updatedAt') or
                                     self.xml.get('addedAt', '1541572987')))))

    def title(self):
        """
        Returns the title of the element as unicode or 'Missing Title'
        """
        return self.xml.get('title', 'Missing Title')

    def sorttitle(self):
        """
        Returns an item's sorting name/title or the title itself if not found
        "Missing Title" if both are not present
        """
        return self.xml.get('titleSort',
                            self.xml.get('title', 'Missing Title'))

    def plex_media_streams(self):
        """
        Returns the media streams directly from the PMS xml.
        Mind to set self.mediastream and self.part before calling this method!
        """
        try:
            return self.xml[self.mediastream][self.part]
        except TypeError:
            # Direct Paths when we don't set mediastream and part
            return self.xml[0][0]

    def part_id(self):
        """
        Returns the unique id of the currently active part [int]
        """
        try:
            return int(self.xml[self.mediastream][self.part].attrib['id'])
        except TypeError:
            # Direct Paths when we don't set mediastream and part
            return int(self.xml[0][0].attrib['id'])

    def plot(self):
        """
        Returns the plot or None.
        """
        return self.xml.get('summary')

    def tagline(self):
        """
        Returns a shorter tagline of the plot or None
        """
        return self.xml.get('tagline')

    def shortplot(self):
        """
        Not yet implemented - returns None
        """
        pass

    def premiere_date(self):
        """
        Returns the "originallyAvailableAt", e.g. "2018-11-16" or None
        """
        return self.xml.get('originallyAvailableAt')

    def kodi_premiere_date(self):
        """
        Takes Plex' originallyAvailableAt of the form "yyyy-mm-dd" and returns
        Kodi's "dd.mm.yyyy" or None
        """
        date = self.premiere_date()
        if date is None:
            return
        try:
            date = sub(r'(\d+)-(\d+)-(\d+)', r'\3.\2.\1', date)
        except Exception:
            date = None
        return date

    def year(self):
        """
        Returns the production(?) year ("year") as Unicode or None
        """
        return self.xml.get('year')

    def studios(self):
        """
        Returns a list of the 'studio' - currently only ever 1 entry.
        Or returns an empty list
        """
        return [self.xml.get('studio')] if self.xml.get('studio') else []

    def content_rating(self):
        """
        Get the content rating or None
        """
        mpaa = self.xml.get('contentRating')
        if not mpaa:
            return
        # Convert more complex cases
        if mpaa in ('NR', 'UR'):
            # Kodi seems to not like NR, but will accept Rated Not Rated
            mpaa = 'Rated Not Rated'
        elif mpaa.startswith('gb/'):
            mpaa = mpaa.replace('gb/', 'UK:', 1)
        return mpaa

    def rating(self):
        """
        Returns the rating [float] first from 'audienceRating', if that fails
        from 'rating'.
        Returns 0.0 if both are not found
        """
        return cast(float, self.xml.get('audienceRating',
                                        self.xml.get('rating'))) or 0.0

    def ratingtype(self):
        """
        Returns the ratingtype [str] first from 'audienceRatingImage'
        (audience) if that fails, from ratingImage (critic). Returns 'default'
        if both are not found
        """
        rtype = 'default'
        # audience ratings
        rtypea = self.xml.get('audienceRatingImage', '')
        if 'rotten' in rtypea:
            rtype = 'tomatometerallaudience'
        elif 'imdb' in rtypea:
            rtype = 'imdb'
        elif 'themoviedb' in rtypea:
            rtype = 'themoviedb'
        elif 'tvdb' in rtypea:
            rtype = 'tvdb'
        elif 'rotten' in self.xml.get('ratingImage', ''):
            # critic ratings - fallback if no audience ratings
            rtype = 'tomatometerallcritics'
        return rtype

    def votecount(self):
        """
        Not implemented by Plex yet - returns None
        """
        pass

    def runtime(self):
        """
        Returns the total duration of the element in seconds as int.
        0 if not found
        """
        runtime = cast(float, self.xml.get('duration')) or 0.0
        return int(runtime * v.PLEX_TO_KODI_TIMEFACTOR)

    def leave_count(self):
        """
        Returns the following dict or None
        {
            'totalepisodes': unicode('leafCount'),
            'watchedepisodes': unicode('viewedLeafCount'),
            'unwatchedepisodes': unicode(totalepisodes - watchedepisodes)
        }
        """
        try:
            total = int(self.xml.attrib['leafCount'])
            watched = int(self.xml.attrib['viewedLeafCount'])
            return {
                'totalepisodes': str(total),
                'watchedepisodes': str(watched),
                'unwatchedepisodes': str(total - watched)
            }
        except (KeyError, TypeError):
            pass

    # Stuff having to do with parent and grandparent items
    ######################################################
    def index(self):
        """
        Returns the 'index' of the element [int]. Depicts e.g. season number of
        the season or the track number of the song
        """
        return cast(int, self.xml.get('index'))

    def show_id(self):
        """
        Returns the episode's tv show's Plex id [int] or None
        """
        return self.grandparent_id()

    def show_title(self):
        """
        Returns the episode's tv show's name/title [unicode] or None
        """
        return self.grandparent_title()

    def season_id(self):
        """
        Returns the episode's season's Plex id [int] or None
        """
        return self.parent_id()

    def season_number(self):
        """
        Returns the episode's season number (e.g. season '2') as an int or None
        """
        return self.parent_index()

    def season_name(self):
        """
        Returns the season's name/title or None
        """
        return self.xml.get('title')

    def artist_name(self):
        """
        Returns the artist name for an album: first it attempts to return
        'parentTitle', if that failes 'originalTitle'
        """
        return self.xml.get('parentTitle', self.xml.get('originalTitle'))

    def parent_id(self):
        """
        Returns the 'parentRatingKey' as int or None
        """
        return cast(int, self.xml.get('parentRatingKey'))

    def parent_index(self):
        """
        Returns the 'parentRatingKey' as int or None
        """
        return cast(int, self.xml.get('parentIndex'))

    def grandparent_id(self):
        """
        Returns the ratingKey for the corresponding grandparent, e.g. a TV show
        for episodes, or None
        """
        return cast(int, self.xml.get('grandparentRatingKey'))

    def grandparent_title(self):
        """
        Returns the title for the corresponding grandparent, e.g. a TV show
        name for episodes, or None
        """
        return self.xml.get('grandparentTitle')

    def disc_number(self):
        """
        Returns the song's disc number as an int or None if not found
        """
        return self.parent_index()

    def _scan_children(self):
        """
        Ensures that we're scanning the xml's subelements only once
        """
        if self._scanned_children:
            return
        self._scanned_children = True
        cast_order = 0
        for child in self.xml:
            if child.tag == 'Role':
                self._cast.append((child.get('tag'),
                                   child.get('thumb'),
                                   child.get('role'),
                                   cast_order))
                cast_order += 1
            elif child.tag == 'Genre':
                self._genres.append(child.get('tag'))
            elif child.tag == 'Country':
                self._countries.append(child.get('tag'))
            elif child.tag == 'Director':
                self._directors.append(child.get('tag'))
            elif child.tag == 'Writer':
                self._writers.append(child.get('tag'))
            elif child.tag == 'Producer':
                self._producers.append(child.get('tag'))
            elif child.tag == 'Location':
                self._locations.append(child.get('path'))
            elif child.tag == 'Collection':
                self._collections.append((cast(int, child.get('id')),
                                         child.get('tag')))
            elif child.tag == 'Guid':
                guid = child.get('id')
                guid = guid.split('://', 1)
                self._guids[guid[0]] = guid[1]
            elif child.tag == 'Marker':
                start = cast(float, child.get('startTimeOffset'))
                end = cast(float, child.get('endTimeOffset'))
                self._markers.append((start / 1000.0,
                                      end / 1000.0,
                                      child.get('type'),
                                      child.get('final') == '1'))
            elif child.tag == 'Label':
                self._labels.append(child.get('tag'))
        # Plex Movie agent (legacy) or "normal" Plex tv show agent
        if not self._guids:
            guid = self.xml.get('guid')
            if not guid:
                return
            for provider, regex in METADATA_PROVIDERS:
                provider_id = regex.findall(guid)
                try:
                    self._guids[provider] = provider_id[0]
                except IndexError:
                    pass
                else:
                    # There will only ever be one entry
                    break

    def cast(self):
        """
        Returns a list of tuples of the cast:
            [(<name of actor [unicode]>,
              <thumb url [unicode, may be None]>,
              <role [unicode, may be None]>,
              <order of appearance [int]>)]
        """
        self._scan_children()
        return self._cast

    def genres(self):
        """
        Returns a list of genres found
        """
        self._scan_children()
        return self._genres

    def countries(self):
        """
        Returns a list of all countries
        """
        self._scan_children()
        return self._countries

    def directors(self):
        """
        Returns a list of all directors
        """

        self._scan_children()
        return self._directors

    def writers(self):
        """
        Returns a list of all writers
        """

        self._scan_children()
        return self._writers

    def producers(self):
        """
        Returns a list of all producers
        """
        self._scan_children()
        return self._producers

    def tv_show_path(self):
        """
        Returns the direct path to the TV show, e.g. '\\NAS\tv\series'
        or None
        """
        self._scan_children()
        if self._locations:
            return self._locations[0]

    def collections(self):
        """
        Returns a list of tuples of the collection id and tags or an empty list
            [(<collection id 1>, <collection name 1>), ...]
        """
        self._scan_children()
        return self._collections

    def people(self):
        """
        Returns a dict with lists of tuples:
        {
            'actor': [(<name of actor [unicode]>,
                       <thumb url [unicode, may be None]>,
                       <role [unicode, may be None]>,
                       <order of appearance [int]>)]
            'director': [..., (<name>, ), ...],
            'writer': [..., (<name>, ), ...]
        }
        Everything in unicode, except <cast order> which is an int.
        Only <art-url> and <role> may be None if not found.
        """
        self._scan_children()
        return {
            'actor': self._cast,
            'director': [(x, ) for x in self._directors],
            'writer': [(x, ) for x in self._writers]
        }

    def labels(self):
        """
        Returns a list of labels found
        """
        self._scan_children()
        return self._labels

    def extras(self):
        """
        Returns an iterator for etree elements for each extra, e.g. trailers
        Returns None if no extras are found
        """
        extras = self.xml.find('Extras')
        if extras is None:
            return
        return (x for x in extras)

    def trailer(self):
        """
        Returns the URL for a single trailer (local trailer preferred; first
        trailer found returned) or an add-on path to list all Plex extras
        if the user setting showExtrasInsteadOfTrailer is set.
        Returns None if nothing is found.
        """
        url = None
        for extras in self.xml.iterfind('Extras'):
            # There will always be only 1 extras element
            if (len(extras) > 0 and
                    app.SYNC.show_extras_instead_of_playing_trailer):
                return ('plugin://%s?mode=route_to_extras&plex_id=%s'
                        % (v.ADDON_ID, self.plex_id))
            for extra in extras:
                typus = cast(int, extra.get('extraType'))
                if typus != 1:
                    # Skip non-trailers
                    continue
                if extra.get('guid', '').startswith('file:'):
                    url = extra.get('ratingKey')
                    # Always prefer local trailers (first one listed)
                    break
                elif not url:
                    url = extra.get('ratingKey')
        if url:
            url = ('plugin://%s.movies/?plex_id=%s&plex_type=%s&mode=play'
                   % (v.ADDON_ID, url, v.PLEX_TYPE_CLIP))
        return url

    def listitem(self, listitem=xbmcgui.ListItem, resume=True):
        """
        Returns a xbmcgui.ListItem() (or PKCListItem) for this Plex element

        Pass resume=False in order to NOT set a resume point (but let Kodi
        automatically handle it)
        """
        item = widgets.generate_item(self)
        if not resume and 'resume' in item:
            del item['resume']
        item = widgets.prepare_listitem(item)
        return widgets.create_listitem(item, as_tuple=False, listitem=listitem)

    def collections_match(self, section_id):
        """
        Downloads one additional xml from the PMS in order to return a list of
        tuples [(collection_id, plex_id), ...] for all collections of the
        current item's Plex library sectin
        Pass in the collection id of e.g. the movie's metadata
        """
        if self._coll_match is None:
            self._coll_match = PF.collections(section_id)
            if self._coll_match is None:
                LOG.error('Could not download collections for %s',
                          self.library_section_id())
                self._coll_match = []
            self._coll_match = \
                [(utils.cast(int, x.get('index')),
                  utils.cast(int, x.get('ratingKey'))) for x in self._coll_match]
        return self._coll_match

    @staticmethod
    def attach_plex_token_to_url(url):
        """
        Returns an extended URL with the Plex token included as 'X-Plex-Token='

        url may or may not already contain a '?'
        """
        if not app.ACCOUNT.pms_token:
            return url
        if '?' not in url:
            return "%s?X-Plex-Token=%s" % (url, app.ACCOUNT.pms_token)
        else:
            return "%s&X-Plex-Token=%s" % (url, app.ACCOUNT.pms_token)

    @staticmethod
    def list_to_string(input_list):
        """
        Concatenates input_list (list of unicodes) with a separator ' / '
        Returns None if the list was empty
        """
        return ' / '.join(input_list) or None
