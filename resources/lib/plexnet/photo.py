# -*- coding: utf-8 -*-
import media
import plexobjects
import plexmedia


class Photo(media.MediaItem):
    TYPE = 'photo'

    def _setData(self, data):
        media.MediaItem._setData(self, data)

        if self.isFullObject():
            self.media = plexobjects.PlexMediaItemList(data, plexmedia.PlexMedia, media.Media.TYPE, initpath=self.initpath, server=self.server, media=self)

    def analyze(self):
        """ The primary purpose of media analysis is to gather information about that media
            item. All of the media you add to a Library has properties that are useful to
            know–whether it's a video file, a music track, or one of your photos.
        """
        self.server.query('/%s/analyze' % self.key)

    def markWatched(self):
        path = '/:/scrobble?key=%s&identifier=com.plexapp.plugins.library' % self.ratingKey
        self.server.query(path)
        self.reload()

    def markUnwatched(self):
        path = '/:/unscrobble?key=%s&identifier=com.plexapp.plugins.library' % self.ratingKey
        self.server.query(path)
        self.reload()

    def play(self, client):
        client.playMedia(self)

    def refresh(self):
        self.server.query('%s/refresh' % self.key, method=self.server.session.put)

    def isPhotoOrDirectoryItem(self):
        return True


class PhotoDirectory(media.MediaItem):
    TYPE = 'photodirectory'

    def all(self):
        path = self.key
        return plexobjects.listItems(self.server, path)

    def isPhotoOrDirectoryItem(self):
        return True


@plexobjects.registerLibFactory('photo')
def PhotoFactory(data, initpath=None, server=None, container=None):
    if data.tag == 'Photo':
        return Photo(data, initpath=initpath, server=server, container=container)
    else:
        return PhotoDirectory(data, initpath=initpath, server=server, container=container)
