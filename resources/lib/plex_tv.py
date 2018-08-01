#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from xbmc import sleep, executebuiltin

from .downloadutils import DownloadUtils as DU
from . import utils
from . import variables as v
from . import state

###############################################################################
LOG = getLogger('PLEX.plex_tx')
###############################################################################


def choose_home_user(token):
    """
    Let's user choose from a list of Plex home users. Will switch to that
    user accordingly.

    Returns a dict:
    {
        'username':             Unicode
        'userid': ''            Plex ID of the user
        'token': ''             User's token
        'protected':            True if PIN is needed, else False
    }

    Will return False if something went wrong (wrong PIN, no connection)
    """
    # Get list of Plex home users
    users = list_home_users(token)
    if not users:
        LOG.error("User download failed.")
        return False
    userlist = []
    userlist_coded = []
    for user in users:
        username = user['title']
        userlist.append(username)
        # To take care of non-ASCII usernames
        userlist_coded.append(utils.try_encode(username))
    usernumber = len(userlist)
    username = ''
    usertoken = ''
    trials = 0
    while trials < 3:
        if usernumber > 1:
            # Select user
            user_select = utils.dialog(
                'select',
                '%s%s' % (utils.lang(29999), utils.lang(39306)),
                userlist_coded)
            if user_select == -1:
                LOG.info("No user selected.")
                utils.settings('username', value='')
                executebuiltin('Addon.Openutils.settings(%s)' % v.ADDON_ID)
                return False
        # Only 1 user received, choose that one
        else:
            user_select = 0
        selected_user = userlist[user_select]
        LOG.info("Selected user: %s", selected_user)
        user = users[user_select]
        # Ask for PIN, if protected:
        pin = None
        if user['protected'] == '1':
            LOG.debug('Asking for users PIN')
            pin = utils.dialog('input',
                               '%s%s' % (utils.lang(39307), selected_user),
                               '',
                               type='{numeric}',
                               option='{hide}')
            # User chose to cancel
            # Plex bug: don't call url for protected user with empty PIN
            if not pin:
                trials += 1
                continue
        # Switch to this Plex Home user, if applicable
        result = switch_home_user(user['id'],
                                  pin,
                                  token,
                                  utils.settings('plex_machineIdentifier'))
        if result:
            # Successfully retrieved username: break out of while loop
            username = result['username']
            usertoken = result['usertoken']
            break
        # Couldn't get user auth
        else:
            trials += 1
            # Could not login user, please try again
            if not utils.dialog('yesno',
                                heading='{plex}',
                                line1='%s%s' % (utils.lang(39308),
                                                selected_user),
                                line2=utils.lang(39309)):
                # User chose to cancel
                break
    if not username:
        LOG.error('Failed signing in a user to plex.tv')
        executebuiltin('Addon.Openutils.settings(%s)' % v.ADDON_ID)
        return False
    return {
        'username': username,
        'userid': user['id'],
        'protected': True if user['protected'] == '1' else False,
        'token': usertoken
    }


def switch_home_user(userid, pin, token, machineIdentifier):
    """
    Retrieves Plex home token for a Plex home user.
    Returns False if unsuccessful

    Input:
        userid          id of the Plex home user
        pin             PIN of the Plex home user, if protected
        token           token for plex.tv

    Output:
        {
            'username'
            'usertoken'         Might be empty strings if no token found
                                for the machineIdentifier that was chosen
        }

    utils.settings('userid') and utils.settings('username') with new plex token
    """
    LOG.info('Switching to user %s', userid)
    url = 'https://plex.tv/api/home/users/' + userid + '/switch'
    if pin:
        url += '?pin=' + pin
    answer = DU().downloadUrl(url,
                              authenticate=False,
                              action_type="POST",
                              headerOptions={'X-Plex-Token': token})
    try:
        answer.attrib
    except AttributeError:
        LOG.error('Error: plex.tv switch HomeUser change failed')
        return False

    username = answer.attrib.get('title', '')
    token = answer.attrib.get('authenticationToken', '')

    # Write to settings file
    utils.settings('username', username)
    utils.settings('accessToken', token)
    utils.settings('userid', answer.attrib.get('id', ''))
    utils.settings('plex_restricteduser',
                   'true' if answer.attrib.get('restricted', '0') == '1'
                   else 'false')
    state.RESTRICTED_USER = True if \
        answer.attrib.get('restricted', '0') == '1' else False

    # Get final token to the PMS we've chosen
    url = 'https://plex.tv/api/resources?includeHttps=1'
    xml = DU().downloadUrl(url,
                           authenticate=False,
                           headerOptions={'X-Plex-Token': token})
    try:
        xml.attrib
    except AttributeError:
        LOG.error('Answer from plex.tv not as excepted')
        # Set to empty iterable list for loop
        xml = []

    found = 0
    LOG.debug('Our machineIdentifier is %s', machineIdentifier)
    for device in xml:
        identifier = device.attrib.get('clientIdentifier')
        LOG.debug('Found a Plex machineIdentifier: %s', identifier)
        if identifier == machineIdentifier:
            found += 1
            token = device.attrib.get('accessToken')

    result = {
        'username': username,
    }
    if found == 0:
        LOG.info('No tokens found for your server! Using empty string')
        result['usertoken'] = ''
    else:
        result['usertoken'] = token
    LOG.info('Plex.tv switch HomeUser change successfull for user %s',
             username)
    return result


def list_home_users(token):
    """
    Returns a list for myPlex home users for the current plex.tv account.

    Input:
        token for plex.tv
    Output:
        List of users, where one entry is of the form:
            "id": userId,
            "admin": '1'/'0',
            "guest": '1'/'0',
            "restricted": '1'/'0',
            "protected": '1'/'0',
            "email": email,
            "title": title,
            "username": username,
            "thumb": thumb_url
        }
    If any value is missing, None is returned instead (or "" from plex.tv)
    If an error is encountered, False is returned
    """
    xml = DU().downloadUrl('https://plex.tv/api/home/users/',
                           authenticate=False,
                           headerOptions={'X-Plex-Token': token})
    try:
        xml.attrib
    except AttributeError:
        LOG.error('Download of Plex home users failed.')
        return False
    users = []
    for user in xml:
        users.append(user.attrib)
    return users


def sign_in_with_pin():
    """
    Prompts user to sign in by visiting https://plex.tv/pin

    Writes to Kodi settings file. Also returns:
    {
        'plexhome':          'true' if Plex Home, 'false' otherwise
        'username':
        'avatar':             URL to user avator
        'token':
        'plexid':             Plex user ID
        'homesize':           Number of Plex home users (defaults to '1')
    }
    Returns False if authentication did not work.
    """
    code, identifier = get_pin()
    if not code:
        # Problems trying to contact plex.tv. Try again later
        utils.dialog('ok', heading='{plex}', line1=utils.lang(39303))
        return False
    # Go to https://plex.tv/pin and enter the code:
    # Or press No to cancel the sign in.
    answer = utils.dialog('yesno',
                          heading='{plex}',
                          line1='%s%s' % (utils.lang(39304), "\n\n"),
                          line2='%s%s' % (code, "\n\n"),
                          line3=utils.lang(39311))
    if not answer:
        return False
    count = 0
    # Wait for approx 30 seconds (since the PIN is not visible anymore :-))
    while count < 30:
        xml = check_pin(identifier)
        if xml is not False:
            break
        # Wait for 1 seconds
        sleep(1000)
        count += 1
    if xml is False:
        # Could not sign in to plex.tv Try again later
        utils.dialog('ok', heading='{plex}', line1=utils.lang(39305))
        return False
    # Parse xml
    userid = xml.attrib.get('id')
    home = xml.get('home', '0')
    if home == '1':
        home = 'true'
    else:
        home = 'false'
    username = xml.get('username', '')
    avatar = xml.get('thumb', '')
    token = xml.findtext('authentication-token')
    home_size = xml.get('homeSize', '1')
    result = {
        'plexhome': home,
        'username': username,
        'avatar': avatar,
        'token': token,
        'plexid': userid,
        'homesize': home_size
    }
    utils.settings('plexLogin', username)
    utils.settings('plexToken', token)
    utils.settings('plexhome', home)
    utils.settings('plexid', userid)
    utils.settings('plexAvatar', avatar)
    utils.settings('plexHomeSize', home_size)
    # Let Kodi log into plex.tv on startup from now on
    utils.settings('myplexlogin', 'true')
    utils.settings('plex_status', value=utils.lang(39227))
    return result


def get_pin():
    """
    For plex.tv sign-in: returns 4-digit code and identifier as 2 str
    """
    code = None
    identifier = None
    # Download
    xml = DU().downloadUrl('https://plex.tv/pins.xml',
                           authenticate=False,
                           action_type="POST")
    try:
        xml.attrib
    except AttributeError:
        LOG.error("Error, no PIN from plex.tv provided")
        return None, None
    code = xml.find('code').text
    identifier = xml.find('id').text
    LOG.info('Successfully retrieved code and id from plex.tv')
    return code, identifier


def check_pin(identifier):
    """
    Checks with plex.tv whether user entered the correct PIN on plex.tv/pin

    Returns False if not yet done so, or the XML response file as etree
    """
    # Try to get a temporary token
    xml = DU().downloadUrl('https://plex.tv/pins/%s.xml' % identifier,
                           authenticate=False)
    try:
        temp_token = xml.find('auth_token').text
    except AttributeError:
        LOG.error("Could not find token in plex.tv answer")
        return False
    if not temp_token:
        return False
    # Use temp token to get the final plex credentials
    xml = DU().downloadUrl('https://plex.tv/users/account',
                           authenticate=False,
                           parameters={'X-Plex-Token': temp_token})
    return xml
