#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
import requests
from threading import Thread

from .common import communicate, log_error, UUIDStr, Subscriber, timeline, \
    stopped_timeline, create_requests_session, proxy_params
from .playqueue import compare_playqueues
from .webserver import ThreadedHTTPServer, CompanionHandlerClassFactory
from .plexgdm import plexgdm

from .. import json_rpc as js
from .. import variables as v
from .. import backgroundthread
from .. import app
from .. import timing


# Disable annoying requests warnings
import requests.packages.urllib3
requests.packages.urllib3.disable_warnings()

log = getLogger('PLEX.companion.playstate')

TIMEOUT = (5, 5)

# How many seconds do we wait until we check again whether we are registered
# as a GDM Plex Companion Client?
GDM_COMPANION_CHECK = 120


def update_player_info(players):
    """
    Update the playstate info for other PKC "consumers"
    """
    for player in players.values():
        playerid = player['playerid']
        app.PLAYSTATE.player_states[playerid].update(js.get_player_props(playerid))
        app.PLAYSTATE.player_states[playerid]['volume'] = js.get_volume()
        app.PLAYSTATE.player_states[playerid]['muted'] = js.get_muted()


class PlaystateMgr(backgroundthread.KillableThread):
    """
    If Kodi plays something, tell the PMS about it and - if a Companion client
    is connected - tell the PMS Plex Companion piece of the PMS about it.
    Also checks whether an intro is currently playing, enabling the user to
    skip it.
    """
    daemon = True

    def __init__(self, companion_enabled):
        self.companion_enabled = companion_enabled
        self.subscribers = dict()
        self.s = None
        self.httpd = None
        self.stopped_timeline = stopped_timeline()
        self.gdm = plexgdm()
        msg = stopped_timeline()
        self.last_pms_msg = {
            0: msg[0].attrib,
            1: msg[1].attrib,
            2: msg[2].attrib
        }
        super().__init__()

    def _start_webserver(self):
        if self.httpd is None and self.companion_enabled:
            log.debug('Starting PKC Companion webserver on port %s', v.COMPANION_PORT)
            server_address = ('', v.COMPANION_PORT)
            HandlerClass = CompanionHandlerClassFactory(self)
            self.httpd = ThreadedHTTPServer(server_address, HandlerClass)
            self.httpd.timeout = 10.0
            t = Thread(target=self.httpd.serve_forever)
            t.start()

    def _stop_webserver(self):
        if self.httpd is not None:
            log.debug('Shutting down PKC Companion webserver')
            try:
                self.httpd.shutdown()
            except AttributeError:
                # Ensure thread-safety
                pass
            self.httpd = None

    def _get_requests_session(self):
        if self.s is None:
            self.s = create_requests_session()
        return self.s

    def _close_requests_session(self):
        if self.s is not None:
            try:
                self.s.close()
            except AttributeError:
                # "thread-safety" - Just in case s was set to None in the
                # meantime
                pass
            self.s = None

    def close_connections(self):
        """May also be called from another thread"""
        with app.APP.lock_subscriber:
            self._stop_webserver()
            self._close_requests_session()
            self.subscribers = dict()

    def send_stop(self):
        """
        If we're still connected to a PMS, tells the PMS that playback stopped
        """
        self.pms_timeline(None, self.stopped_timeline)
        self.companion_timeline(self.stopped_timeline)

    def check_subscriber(self, cmd):
        if not cmd.get('clientIdentifier'):
            return
        uuid = UUIDStr(cmd.get('clientIdentifier'))
        with app.APP.lock_subscriber:
            if cmd.get('path') == '/player/timeline/unsubscribe':
                if uuid in self.subscribers:
                    log.debug('Stop Plex Companion subscription for %s', uuid)
                    del self.subscribers[uuid]
            elif uuid not in self.subscribers:
                log.debug('Start new Plex Companion subscription for %s', uuid)
                self.subscribers[uuid] = Subscriber(self, cmd=cmd)
            else:
                try:
                    self.subscribers[uuid].command_id = int(cmd.get('commandID'))
                except TypeError:
                    pass

    def subscribe(self, uuid, command_id, url):
        log.debug('New Plex Companion subscriber %s: %s', uuid, url)
        with app.APP.lock_subscriber:
            self.subscribers[UUIDStr(uuid)] = Subscriber(self,
                                                         cmd=None,
                                                         uuid=uuid,
                                                         command_id=command_id,
                                                         url=url)

    def unsubscribe(self, uuid):
        log.debug('Unsubscribing Plex Companion client %s', uuid)
        with app.APP.lock_subscriber:
            try:
                del self.subscribers[UUIDStr(uuid)]
            except KeyError:
                pass

    def update_command_id(self, uuid, command_id):
        with app.APP.lock_subscriber:
            if uuid not in self.subscribers:
                return False
            self.subscribers[uuid].command_id = command_id
        return True

    def companion_timeline(self, message):
        state = 'stopped'
        for entry in message:
            if entry.get('state') != 'stopped':
                state = entry.get('state')
        with app.APP.lock_subscriber:
            for subscriber in self.subscribers.values():
                subscriber.send_timeline(message, state)

    def pms_timeline_per_player(self, playerid, message):
        """
        Sending the "normal", non-Companion playstate to the PMS works a bit
        differently
        """
        url = f'{app.CONN.server}/:/timeline'
        self._get_requests_session()
        if message[playerid].attrib.get('state') != 'stopped':
            params = proxy_params()
            params.update(message[playerid].attrib)
            self.last_pms_msg[playerid] = params
        else:
            self.last_pms_msg[playerid].update({'state': 'stopped'})
            params = self.last_pms_msg[playerid]
        # Tell the PMS about our playstate progress
        try:
            req = communicate(self.s.get,
                              url,
                              timeout=TIMEOUT,
                              params=params)
        except requests.RequestException as error:
            log.error('Could not send the PMS timeline: %s', error)
            return
        except SystemExit:
            return
        if not req.ok:
            log_error(log.error, 'Failed reporting playback progress', req)

    def pms_timeline(self, players, message):
        players = players if players else \
            {0: {'playerid': 0}, 1: {'playerid': 1}, 2: {'playerid': 2}}
        for player in players.values():
            self.pms_timeline_per_player(player['playerid'], message)

    def wait_while_suspended(self):
        should_shutdown = super().wait_while_suspended()
        if not should_shutdown:
            self._start_webserver()
        return should_shutdown

    def run(self):
        app.APP.register_thread(self)
        log.info("----===## Starting PlaystateMgr ##===----")
        try:
            self._run()
        finally:
            # Make sure we're telling the PMS that playback will stop
            self.send_stop()
            # Cleanup
            self.close_connections()
            app.APP.deregister_thread(self)
            log.info("----===## PlaystateMgr stopped ##===----")

    def _run(self):
        signaled_playback_stop = True
        self._start_webserver()
        self.gdm.start()
        last_check = timing.unix_timestamp()
        while not self.should_cancel():
            if self.should_suspend():
                self.close_connections()
                if self.wait_while_suspended():
                    break
            # Check for Kodi playlist changes first
            with app.APP.lock_playqueues:
                for playqueue in app.PLAYQUEUES:
                    kodi_pl = js.playlist_get_items(playqueue.playlistid)
                    if playqueue.old_kodi_pl != kodi_pl:
                        if playqueue.id is None and (not app.SYNC.direct_paths or
                                                     app.PLAYSTATE.context_menu_play):
                            # Only initialize if directly fired up using direct
                            # paths. Otherwise let default.py do its magic
                            log.debug('Not yet initiating playback')
                        else:
                            # compare old and new playqueue
                            compare_playqueues(playqueue, kodi_pl)
                        playqueue.old_kodi_pl = list(kodi_pl)
            # Make sure we are registered as a player
            now = timing.unix_timestamp()
            if now - last_check > GDM_COMPANION_CHECK:
                self.gdm.check_client_registration()
                last_check = now
            # Then check for Kodi playback
            players = js.get_players()
            if not players and signaled_playback_stop:
                self.sleep(1)
                continue
            elif not players:
                # Playback has just stopped, need to tell Plex
                self.send_stop()
                signaled_playback_stop = True
                self.sleep(1)
                continue
            elif not app.PLAYSTATE.item:
                # Not a Plex item currently playing
                self.sleep(1)
                continue
            else:
                # Update the playstate info, such as playback progress
                update_player_info(players)
                try:
                    message = timeline(players)
                except (TypeError, IndexError):
                    # We haven't had a chance to set the kodi_stream_index for
                    # the currently playing item. Just skip for now
                    self.sleep(1)
                    continue
                else:
                    # Kodi will started with 'stopped' - make sure we're
                    # waiting here until we got something playing or on pause.
                    for entry in message:
                        if entry.get('state') != 'stopped':
                            break
                    else:
                        continue
                    signaled_playback_stop = False
            # Send the playback progress info to the PMS
            self.pms_timeline(players, message)
            # Send the info to all Companion devices via the PMS
            self.companion_timeline(message)
            self.sleep(1)
