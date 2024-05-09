#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
from .. import utils, variables as v, app


LOG = getLogger('PLEX.api.file')

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
    def fullpath(self, force_first_media=True, force_addon=False,
             direct_paths=None, omit_check=False, force_check=False):
        """
        Returns a "fully qualified path" add-on paths or direct paths
        depending on the current settings as the tupple
            (fullpath, path, filename)
        as unicode. Add-on paths are returned as a fallback. Returns None
        if something went wrong.

        firce_first_media=False prompts the user to choose which version of the
                                media should be returned, if several are present
        force_addon=True will always return the add-on path
        direct_path=True if you're calling from another Plex python
                         instance - because otherwise direct paths will
                         evaluate to False!
        """
        direct_paths = app.SYNC.direct_paths if direct_paths is None \
            else direct_paths
        if (not direct_paths or force_addon or
                self.plex_type == v.PLEX_TYPE_CLIP):
            if self.plex_type == v.PLEX_TYPE_SONG:
                return self._music_addon_paths(force_first_media)
            if self.plex_type == v.PLEX_TYPE_EPISODE:
                # need to include the plex show id in the path
                path = ('plugin://plugin.video.plexkodiconnect.tvshows/%s/'
                        % self.grandparent_id())
            else:
                path = 'plugin://%s/' % v.ADDON_TYPE[self.plex_type]
            # Filename in Kodi will end with actual filename - hopefully
            # this is useful for other add-ons
            filename = self.file_path(force_first_media=force_first_media)
            if filename:
                if '/' in filename:
                    filename = filename.rsplit('/', 1)[1]
                else:
                    filename = filename.rsplit('\\', 1)[1]
                entirepath = ('%s?mode=play&plex_id=%s&plex_type=%s&filename=%s'
                        % (path, self.plex_id, self.plex_type, filename))
            else:
                # E.g. clips or albums
                entirepath = ('%s?mode=play&plex_id=%s&plex_type=%s'
                        % (path, self.plex_id, self.plex_type))
            # For Kodi DB, we need to safe the ENTIRE path for filenames
            filename = entirepath
        else:
            entirepath = self.validate_playurl(
                self.file_path(force_first_media=force_first_media),
                self.plex_type,
                force_check=force_check,
                omit_check=omit_check)
            try:
                if '/' in entirepath:
                    filename = entirepath.rsplit('/', 1)[1]
                else:
                    filename = entirepath.rsplit('\\', 1)[1]
            except (TypeError, IndexError):
                # Fallback to add-on paths
                return self.fullpath(force_first_media=force_first_media,
                                     force_addon=True)
            path = utils.rreplace(entirepath, filename, "", 1)
        return entirepath, path, filename

    def _music_addon_paths(self, force_first_media):
        """
        For songs only. Normal add-on paths plugin://... don't work with the
        Kodi music DB, hence use a "direct" url to the music file on the PMS.
        """
        if self.mediastream is None and force_first_media is False:
            if self.mediastream_number() is None:
                return
        streamno = 0 if force_first_media else self.mediastream
        entirepath = "%s%s" % (app.CONN.server,
                               self.xml[streamno][self.part].get('key'))
        entirepath = self.attach_plex_token_to_url(entirepath)
        path, filename = entirepath.rsplit('/', 1)
        return entirepath, path + '/', filename

    def directory_path(self, section_id=None, plex_type=None, old_key=None,
                       synched=True):
        key = self.xml.get('fastKey')
        if not key:
            key = self.xml.get('key')
            LOG.debug('directory_path. section_id: %s, key: %s, old_key: %s', section_id, key, old_key)
            # the key returned by plex might be an absolute path, ex: "/library/sections/1/folder?parent=3030"
            # we should directly use the key if it starts with a slash
            if not key.startswith('/'):
                if old_key:
                    key = '%s/%s' % (old_key, key)
                else:
                    key = '/library/sections/%s/%s' % (section_id, key)
                LOG.debug('directory_path. browseplex key will be "%s"', key)
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
