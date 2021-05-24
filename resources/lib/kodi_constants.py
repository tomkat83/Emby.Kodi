#!/usr/bin/python
# -*- coding: utf-8 -*-
'''
script.module.metadatautils
kodi_constants.py
Several common constants for use with Kodi json api
'''
FIELDS_BASE = ["dateadded", "file", "lastplayed", "plot", "title", "art", "playcount"]
FIELDS_FILE = FIELDS_BASE + ["streamdetails", "director", "resume", "runtime"]
FIELDS_MOVIES = FIELDS_FILE + ["plotoutline", "sorttitle", "cast", "votes", "showlink", "top250", "trailer", "year",
                               "country", "studio", "set", "genre", "mpaa", "setid", "rating", "tag", "tagline",
                               "writer", "originaltitle",
                               "imdbnumber"]
FIELDS_MOVIES.append("uniqueid")
FIELDS_TVSHOWS = FIELDS_BASE + ["sorttitle", "mpaa", "premiered", "year", "episode", "watchedepisodes", "votes",
                                "rating", "studio", "season", "genre", "cast", "episodeguide", "tag", "originaltitle",
                                "imdbnumber"]
FIELDS_SEASON = ['art', 'playcount', 'season', 'showtitle', 'episode',
                 'tvshowid', 'watchedepisodes', 'userrating', 'fanart', 'thumbnail']
FIELDS_EPISODES = FIELDS_FILE + ["cast", "productioncode", "rating", "votes", "episode", "showtitle", "tvshowid",
                                 "season", "firstaired", "writer", "originaltitle"]
FIELDS_MUSICVIDEOS = FIELDS_FILE + ["genre", "artist", "tag", "album", "track", "studio", "year"]
FIELDS_FILES = FIELDS_FILE + ["plotoutline", "sorttitle", "cast", "votes", "trailer", "year", "country", "studio",
                              "genre", "mpaa", "rating", "tagline", "writer", "originaltitle", "imdbnumber",
                              "premiered", "episode", "showtitle",
                              "firstaired", "watchedepisodes", "duration", "season"]
FIELDS_SONGS = ["artist", "displayartist", "title", "rating", "fanart", "thumbnail", "duration", "disc",
                "playcount", "comment", "file", "album", "lastplayed", "genre", "musicbrainzartistid", "track",
                "dateadded"]
FIELDS_ALBUMS = ["title", "fanart", "thumbnail", "genre", "displayartist", "artist",
                 "musicbrainzalbumartistid", "year", "rating", "artistid", "musicbrainzalbumid", "theme", "description",
                 "type", "style", "playcount", "albumlabel", "mood", "dateadded"]
FIELDS_ARTISTS = ["born", "formed", "died", "style", "yearsactive", "mood", "fanart", "thumbnail",
                  "musicbrainzartistid", "disbanded", "description", "instrument"]
FIELDS_RECORDINGS = ["art", "channel", "directory", "endtime", "file", "genre", "icon", "playcount", "plot",
                     "plotoutline", "resume", "runtime", "starttime", "streamurl", "title"]
FIELDS_CHANNELS = ["broadcastnow", "channeltype", "hidden", "locked", "lastplayed", "thumbnail", "channel"]

FILTER_UNWATCHED = {"operator": "lessthan", "field": "playcount", "value": "1"}
FILTER_WATCHED = {"operator": "isnot", "field": "playcount", "value": "0"}
FILTER_RATING = {"operator": "greaterthan", "field": "rating", "value": "7"}
FILTER_RATING_MUSIC = {"operator": "greaterthan", "field": "rating", "value": "3"}
FILTER_INPROGRESS = {"operator": "true", "field": "inprogress", "value": ""}
SORT_RATING = {"method": "rating", "order": "descending"}
SORT_RANDOM = {"method": "random", "order": "descending"}
SORT_TITLE = {"method": "title", "order": "ascending"}
SORT_DATEADDED = {"method": "dateadded", "order": "descending"}
SORT_LASTPLAYED = {"method": "lastplayed", "order": "descending"}
SORT_EPISODE = {"method": "episode"}
