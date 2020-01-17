#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals

from builtins import object
from .. import utils, variables as v, app


def _transcode_image_path(key, AuthToken, path, width, height):
    """
    Transcode Image support

    parameters:
        key
        AuthToken
        path - source path of current XML: path[srcXML]
        width
        height
    result:
        final path to image file
    """
    # external address - can we get a transcoding request for external images?
    if key.startswith('http'):
        path = key
    elif key.startswith('/'):  # internal full path.
        path = 'http://127.0.0.1:32400' + key
    else:  # internal path, add-on
        path = 'http://127.0.0.1:32400' + path + '/' + key
    # This is bogus (note the extra path component) but ATV is stupid when it
    # comes to caching images, it doesn't use querystrings. Fortunately PMS is
    # lenient...
    transcode_path = ('/photo/:/transcode/%sx%s/%s'
                      % (width, height, utils.quote_plus(path)))
    args = {
        'width': width,
        'height': height,
        'url': path
    }
    if AuthToken:
        args['X-Plex-Token'] = AuthToken
    return utils.extend_url(transcode_path, args)


class File(object):
    def path(self, force_first_media=True, force_addon=False,
             direct_paths=None):
        """
        Returns a "fully qualified path": add-on paths or direct paths
        depending on the current settings. Will NOT valide the playurl
        Returns unicode or None if something went wrong.

        Pass direct_path=True if you're calling from another Plex python
        instance - because otherwise direct paths will evaluate to False!
        """
        direct_paths = direct_paths or app.SYNC.direct_paths
        filename = self.file_path(force_first_media=force_first_media)
        if (not direct_paths or force_addon or
                self.plex_type == v.PLEX_TYPE_CLIP):
            if filename and '/' in filename:
                filename = filename.rsplit('/', 1)
            elif filename:
                filename = filename.rsplit('\\', 1)
            try:
                filename = filename[1]
            except (TypeError, IndexError):
                filename = None
            # Set plugin path and media flags using real filename
            if self.plex_type == v.PLEX_TYPE_EPISODE:
                # need to include the plex show id in the path
                path = ('plugin://plugin.video.plexkodiconnect.tvshows/%s/'
                        % self.grandparent_id())
            else:
                path = 'plugin://%s/' % v.ADDON_TYPE[self.plex_type]
            path = ('%s?plex_id=%s&plex_type=%s&mode=play&filename=%s'
                    % (path, self.plex_id, self.plex_type, filename))
        else:
            # Direct paths is set the Kodi way
            path = self.validate_playurl(filename,
                                         self.plex_type,
                                         omit_check=True)
        return path

    def directory_path(self, section_id=None, plex_type=None, old_key=None,
                       synched=True):
        key = self.xml.get('fastKey')
        if not key:
            key = self.xml.get('key')
            if old_key:
                key = '%s/%s' % (old_key, key)
            elif not key.startswith('/'):
                key = '/library/sections/%s/%s' % (section_id, key)
        params = {
            'mode': 'browseplex',
            'key': key
        }
        if plex_type or self.plex_type:
            params['plex_type'] = plex_type or self.plex_type
        if not synched:
            # No item to be found in the Kodi DB
            params['synched'] = 'false'
        if self.xml.get('prompt'):
            # User input needed, e.g. search for a movie or episode
            params['prompt'] = self.xml.get('prompt')
        if section_id:
            params['id'] = section_id
        return utils.extend_url('plugin://%s/' % v.ADDON_ID, params)

    def file_name(self, force_first_media=False):
        """
        Returns only the filename, e.g. 'movie.mkv' as unicode or None if not
        found
        """
        ans = self.file_path(force_first_media=force_first_media)
        if ans is None:
            return
        if "\\" in ans:
            # Local path
            filename = ans.rsplit("\\", 1)[1]
        else:
            try:
                # Network share
                filename = ans.rsplit("/", 1)[1]
            except IndexError:
                # E.g. certain Plex channels
                filename = None
        return filename

    def file_path(self, force_first_media=False):
        """
        Returns the direct path to this item, e.g. '\\NAS\movies\movie.mkv'
        as unicode or None

        force_first_media=True:
            will always use 1st media stream, e.g. when several different
            files are present for the same PMS item
        """
        if self.mediastream is None and force_first_media is False:
            if self.mediastream_number() is None:
                return
        try:
            if force_first_media is False:
                ans = self.xml[self.mediastream][self.part].attrib['file']
            else:
                ans = self.xml[0][self.part].attrib['file']
        except (TypeError, AttributeError, IndexError, KeyError):
            return
        return ans

    def get_picture_path(self):
        """
        Returns the item's picture path (transcode, if necessary) as string.
        Will always use addon paths, never direct paths
        """
        path = self.xml[0][0].get('key')
        extension = path[path.rfind('.'):].lower()
        if app.SYNC.force_transcode_pix or extension not in v.KODI_SUPPORTED_IMAGES:
            # Let Plex transcode
            # max width/height supported by plex image transcoder is 1920x1080
            path = app.CONN.server + _transcode_image_path(
                path,
                app.ACCOUNT.pms_token,
                "%s%s" % (app.CONN.server, path),
                1920,
                1080)
        else:
            path = self.attach_plex_token_to_url('%s%s' % (app.CONN.server, path))
        # Attach Plex id to url to let it be picked up by our playqueue agent
        # later
        return '%s&plex_id=%s' % (path, self.plex_id)
