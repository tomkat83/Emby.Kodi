# -*- coding: utf-8 -*-

###############################################################################

import json
import requests
import os
import urllib
from sqlite3 import OperationalError

import xbmc
import xbmcgui
import xbmcvfs

import utils
import image_cache_thread

# Disable annoying requests warnings
import requests.packages.urllib3
requests.packages.urllib3.disable_warnings()

###############################################################################


@utils.logging
class Artwork():
    xbmc_host = 'localhost'
    xbmc_port = None
    xbmc_username = None
    xbmc_password = None
    
    imageCacheThreads = []
    imageCacheLimitThreads = 0

    def __init__(self):

        self.enableTextureCache = utils.settings('enableTextureCache') == "true"
        self.imageCacheLimitThreads = int(utils.settings("imageCacheLimit"))
        self.imageCacheLimitThreads = int(self.imageCacheLimitThreads * 5);
        utils.logMsg("Using Image Cache Thread Count: " + str(self.imageCacheLimitThreads), 1)
        
        if not self.xbmc_port and self.enableTextureCache:
            self.setKodiWebServerDetails()

        self.userId = utils.window('currUserId')
        self.server = utils.window('pms_server')

    def double_urlencode(self, text):
        text = self.single_urlencode(text)
        text = self.single_urlencode(text)
        
        return text

    def single_urlencode(self, text):
        
        text = urllib.urlencode({'blahblahblah':text.encode("utf-8")}) #urlencode needs a utf- string
        text = text[13:]

        return text.decode("utf-8") #return the result again as unicode

    def setKodiWebServerDetails(self):
        # Get the Kodi webserver details - used to set the texture cache
        web_query = {

            "jsonrpc": "2.0",
            "id": 1,
            "method": "Settings.GetSettingValue",
            "params": {

                "setting": "services.webserver"
            }
        }
        result = xbmc.executeJSONRPC(json.dumps(web_query))
        result = json.loads(result)
        try:
            xbmc_webserver_enabled = result['result']['value']
        except KeyError, TypeError:
            xbmc_webserver_enabled = False
            
        if not xbmc_webserver_enabled:
            # Enable the webserver, it is disabled
            web_port = {

                "jsonrpc": "2.0",
                "id": 1,
                "method": "Settings.SetSettingValue",
                "params": {

                    "setting": "services.webserverport",
                    "value": 8080
                }
            }
            result = xbmc.executeJSONRPC(json.dumps(web_port))
            self.xbmc_port = 8080

            web_user = {

                "jsonrpc": "2.0",
                "id": 1,
                "method": "Settings.SetSettingValue",
                "params": {

                    "setting": "services.webserver",
                    "value": True
                }
            }
            result = xbmc.executeJSONRPC(json.dumps(web_user))
            self.xbmc_username = "kodi"


        # Webserver already enabled
        web_port = {

            "jsonrpc": "2.0",
            "id": 1,
            "method": "Settings.GetSettingValue",
            "params": {

                "setting": "services.webserverport"
            }
        }
        result = xbmc.executeJSONRPC(json.dumps(web_port))
        result = json.loads(result)
        try:
            self.xbmc_port = result['result']['value']
        except TypeError:
            pass

        web_user = {

            "jsonrpc": "2.0",
            "id": 1,
            "method": "Settings.GetSettingValue",
            "params": {

                "setting": "services.webserverusername"
            }
        }
        result = xbmc.executeJSONRPC(json.dumps(web_user))
        result = json.loads(result)
        try:
            self.xbmc_username = result['result']['value']
        except TypeError:
            pass

        web_pass = {

            "jsonrpc": "2.0",
            "id": 1,
            "method": "Settings.GetSettingValue",
            "params": {

                "setting": "services.webserverpassword"
            }
        }
        result = xbmc.executeJSONRPC(json.dumps(web_pass))
        result = json.loads(result)
        try:
            self.xbmc_password = result['result']['value']
        except TypeError:
            pass
    
    def FullTextureCacheSync(self):
        # This method will sync all Kodi artwork to textures13.db
        # and cache them locally. This takes diskspace!
        import xbmcaddon
        string = xbmcaddon.Addon().getLocalizedString

        if not xbmcgui.Dialog().yesno(
            "Image Texture Cache", string(39250).encode('utf-8')):
            return
            
        self.logMsg("Doing Image Cache Sync", 1)
        
        dialog = xbmcgui.DialogProgress()
        dialog.create("Emby for Kodi", "Image Cache Sync")
            
        # ask to rest all existing or not
        if xbmcgui.Dialog().yesno(
            "Image Texture Cache", string(39251).encode('utf-8'), ""):
            self.logMsg("Resetting all cache data first", 1)
            # Remove all existing textures first
            path = xbmc.translatePath("special://thumbnails/").decode('utf-8')
            if utils.IfExists(path):
                allDirs, allFiles = xbmcvfs.listdir(path)
                for dir in allDirs:
                    allDirs, allFiles = xbmcvfs.listdir(path+dir)
                    for file in allFiles:
                        if os.path.supports_unicode_filenames:
                            xbmcvfs.delete(os.path.join(path+dir.decode('utf-8'),file.decode('utf-8')))
                        else:
                            xbmcvfs.delete(os.path.join(path.encode('utf-8')+dir,file))
            
            # remove all existing data from texture DB
            textureconnection = utils.kodiSQL('texture')
            texturecursor = textureconnection.cursor()
            texturecursor.execute('SELECT tbl_name FROM sqlite_master WHERE type="table"')
            rows = texturecursor.fetchall()
            for row in rows:
                tableName = row[0]
                if(tableName != "version"):
                    texturecursor.execute("DELETE FROM " + tableName)
            textureconnection.commit()
            texturecursor.close()

        # Cache all entries in video DB
        connection = utils.kodiSQL('video')
        cursor = connection.cursor()
        cursor.execute("SELECT url FROM art WHERE media_type != 'actor'") # dont include actors
        result = cursor.fetchall()
        total = len(result)
        count = 1     
        percentage = 0  
        self.logMsg("Image cache sync about to process " + str(total) + " images", 1)
        for url in result:
            if dialog.iscanceled():
                break
            percentage = int((float(count) / float(total))*100)
            textMessage = str(count) + " of " + str(total) + " (" + str(len(self.imageCacheThreads)) + ")"
            dialog.update(percentage, "Updating Image Cache: " + textMessage)
            self.CacheTexture(url[0])
            count += 1
        cursor.close()
        
        # Cache all entries in music DB
        connection = utils.kodiSQL('music')
        cursor = connection.cursor()
        cursor.execute("SELECT url FROM art")
        result = cursor.fetchall()
        total = len(result)
        count = 1     
        percentage = 0
        self.logMsg("Image cache sync about to process " + str(total) + " images", 1)
        for url in result:
            if dialog.iscanceled():
                break        
            percentage = int((float(count) / float(total))*100)
            textMessage = str(count) + " of " + str(total)
            dialog.update(percentage, "Updating Image Cache: " + textMessage)
            self.CacheTexture(url[0])
            count += 1
        cursor.close()
        
        dialog.update(100, "Waiting for all threads to exit: " + str(len(self.imageCacheThreads)))
        self.logMsg("Waiting for all threads to exit", 1)
        while len(self.imageCacheThreads) > 0:
            for thread in self.imageCacheThreads:
                if thread.isFinished:
                    self.imageCacheThreads.remove(thread)
            dialog.update(100, "Waiting for all threads to exit: " + str(len(self.imageCacheThreads)))
            self.logMsg("Waiting for all threads to exit: " + str(len(self.imageCacheThreads)), 1)
            xbmc.sleep(500)
        
        dialog.close()

    def addWorkerImageCacheThread(self, urlToAdd):
    
        while(True):
            # removed finished
            for thread in self.imageCacheThreads:
                if thread.isFinished:
                    self.imageCacheThreads.remove(thread)    

            # add a new thread or wait and retry if we hit our limit
            if(len(self.imageCacheThreads) < self.imageCacheLimitThreads):
                newThread = image_cache_thread.image_cache_thread()
                newThread.setUrl(self.double_urlencode(urlToAdd))
                newThread.setHost(self.xbmc_host, self.xbmc_port)
                newThread.setAuth(self.xbmc_username, self.xbmc_password)
                newThread.start()
                self.imageCacheThreads.append(newThread)
                return
            else:
                self.logMsg("Waiting for empty queue spot: " + str(len(self.imageCacheThreads)), 2)
                xbmc.sleep(50)
         
        
    def CacheTexture(self, url):
        # Cache a single image url to the texture cache
        if url and self.enableTextureCache:
            if(self.imageCacheLimitThreads == 0 or self.imageCacheLimitThreads == None):
                #Add image to texture cache by simply calling it at the http endpoint
                
                url = self.double_urlencode(url)
                try: # Extreme short timeouts so we will have a exception.
                    response = requests.head(
                                        url=(
                                            "http://%s:%s/image/image://%s"
                                            % (self.xbmc_host, self.xbmc_port, url)),
                                        auth=(self.xbmc_username, self.xbmc_password),
                                        timeout=(0.01, 0.01))
                # We don't need the result
                except: pass
                
            else:
                self.addWorkerImageCacheThread(url)

       
    def addArtwork(self, artwork, kodiId, mediaType, cursor):
        # Kodi conversion table
        kodiart = {

            'Primary': ["thumb", "poster"],
            'Banner': "banner",
            'Logo': "clearlogo",
            'Art': "clearart",
            'Thumb': "landscape",
            'Disc': "discart",
            'Backdrop': "fanart",
            'BoxRear': "poster"
        }

        # Artwork is a dictionary
        for art in artwork:
            if art == "Backdrop":
                # Backdrop entry is a list
                # Process extra fanart for artwork downloader (fanart, fanart1, fanart2...)
                backdrops = artwork[art]
                backdropsNumber = len(backdrops)

                query = ' '.join((

                    "SELECT url",
                    "FROM art",
                    "WHERE media_id = ?",
                    "AND media_type = ?",
                    "AND type LIKE ?"
                ))
                cursor.execute(query, (kodiId, mediaType, "fanart%",))
                rows = cursor.fetchall()

                if len(rows) > backdropsNumber:
                    # More backdrops in database. Delete extra fanart.
                    query = ' '.join((

                        "DELETE FROM art",
                        "WHERE media_id = ?",
                        "AND media_type = ?",
                        "AND type LIKE ?"
                    ))
                    cursor.execute(query, (kodiId, mediaType, "fanart_",))

                # Process backdrops and extra fanart
                index = ""
                for backdrop in backdrops:
                    self.addOrUpdateArt(
                        imageUrl=backdrop,
                        kodiId=kodiId,
                        mediaType=mediaType,
                        imageType="%s%s" % ("fanart", index),
                        cursor=cursor)
                    
                    if backdropsNumber > 1:
                        try: # Will only fail on the first try, str to int.
                            index += 1
                        except TypeError:
                            index = 1
                
            elif art == "Primary":
                # Primary art is processed as thumb and poster for Kodi.
                for artType in kodiart[art]:
                    self.addOrUpdateArt(
                        imageUrl=artwork[art],
                        kodiId=kodiId,
                        mediaType=mediaType,
                        imageType=artType,
                        cursor=cursor)
            
            elif kodiart.get(art):
                # Process the rest artwork type that Kodi can use
                self.addOrUpdateArt(
                    imageUrl=artwork[art],
                    kodiId=kodiId,
                    mediaType=mediaType,
                    imageType=kodiart[art],
                    cursor=cursor)

    def addOrUpdateArt(self, imageUrl, kodiId, mediaType, imageType, cursor):
        # Possible that the imageurl is an empty string
        if imageUrl:
            cacheimage = False

            query = ' '.join((

                "SELECT url",
                "FROM art",
                "WHERE media_id = ?",
                "AND media_type = ?",
                "AND type = ?"
            ))
            cursor.execute(query, (kodiId, mediaType, imageType,))
            try: # Update the artwork
                url = cursor.fetchone()[0]
            
            except TypeError: # Add the artwork
                cacheimage = True
                query = (
                    '''
                    INSERT INTO art(media_id, media_type, type, url)

                    VALUES (?, ?, ?, ?)
                    '''
                )
                cursor.execute(query, (kodiId, mediaType, imageType, imageUrl))
            
            else: # Only cache artwork if it changed
                if url != imageUrl:
                    cacheimage = True
                    
                    # Only for the main backdrop, poster
                    if (utils.window('emby_initialScan') != "true" and
                            imageType in ("fanart", "poster")):
                        # Delete current entry before updating with the new one
                        self.deleteCachedArtwork(url)

                    query = ' '.join((

                        "UPDATE art",
                        "SET url = ?",
                        "WHERE media_id = ?",
                        "AND media_type = ?",
                        "AND type = ?"
                    ))
                    cursor.execute(query, (imageUrl, kodiId, mediaType, imageType))
                    
            # Cache fanart and poster in Kodi texture cache
            if cacheimage and imageType in ("fanart", "poster", "thumb"):
                self.CacheTexture(imageUrl)

    def deleteArtwork(self, kodiid, mediatype, cursor):

        query = ' '.join((

            "SELECT url, type",
            "FROM art",
            "WHERE media_id = ?",
            "AND media_type = ?"
        ))
        cursor.execute(query, (kodiid, mediatype,))
        rows = cursor.fetchall()
        for row in rows:

            url = row[0]
            imagetype = row[1]
            if imagetype in ("poster", "fanart"):
                self.deleteCachedArtwork(url)

    def deleteCachedArtwork(self, url):
        # Only necessary to remove and apply a new backdrop or poster
        connection = utils.kodiSQL('texture')
        cursor = connection.cursor()

        try:
            cursor.execute("SELECT cachedurl FROM texture WHERE url = ?", (url,))
            cachedurl = cursor.fetchone()[0]
        
        except TypeError:
            self.logMsg("Could not find cached url.", 1)

        except OperationalError:
            self.logMsg("Database is locked. Skip deletion process.", 1)
        
        else: # Delete thumbnail as well as the entry
            thumbnails = xbmc.translatePath("special://thumbnails/%s" % cachedurl).decode('utf-8')
            self.logMsg("Deleting cached thumbnail: %s" % thumbnails, 1)
            xbmcvfs.delete(thumbnails)
            
            try:
                cursor.execute("DELETE FROM texture WHERE url = ?", (url,))
                connection.commit()
            except OperationalError:
                self.logMsg("Issue deleting url from cache. Skipping.", 2)
        
        finally:
            cursor.close()

    def getPeopleArtwork(self, people):
        # append imageurl if existing
        for person in people:

            personId = person['Id']
            tag = person.get('PrimaryImageTag')

            image = ""
            if tag:
                image = (
                    "%s/emby/Items/%s/Images/Primary?"
                    "MaxWidth=400&MaxHeight=400&Index=0&Tag=%s"
                    % (self.server, personId, tag))
            
            person['imageurl'] = image

        return people

    def getUserArtwork(self, itemid, itemtype):
        # Load user information set by UserClient
        image = ("%s/emby/Users/%s/Images/%s?Format=original"
                    % (self.server, itemid, itemtype))
        return image


def getAllArtwork(self, item, parentInfo=False):

        server = self.server

        itemid = item['Id']
        artworks = item['ImageTags']
        backdrops = item.get('BackdropImageTags',[])

        maxHeight = 10000
        maxWidth = 10000
        customquery = ""

        # if utils.settings('compressArt') == "true":
        #     customquery = "&Quality=90"

        # if utils.settings('enableCoverArt') == "false":
        #     customquery += "&EnableImageEnhancers=false"

        allartworks = {

            'Primary': "",
            'Art': "",
            'Banner': "",
            'Logo': "",
            'Thumb': "",
            'Disc': "",
            'Backdrop': []
        }
        
        # Process backdrops
        for index, tag in enumerate(backdrops):
            artwork = (
                "%s/emby/Items/%s/Images/Backdrop/%s?"
                "MaxWidth=%s&MaxHeight=%s&Format=original&Tag=%s%s"
                % (server, itemid, index, maxWidth, maxHeight, tag, customquery))
            allartworks['Backdrop'].append(artwork)

        # Process the rest of the artwork
        for art in artworks:
            # Filter backcover
            if art != "BoxRear":
                tag = artworks[art]
                artwork = (
                    "%s/emby/Items/%s/Images/%s/0?"
                    "MaxWidth=%s&MaxHeight=%s&Format=original&Tag=%s%s"
                    % (server, itemid, art, maxWidth, maxHeight, tag, customquery))
                allartworks[art] = artwork

        # Process parent items if the main item is missing artwork
        if parentInfo:
            
            # Process parent backdrops
            if not allartworks['Backdrop']:
                
                parentId = item.get('ParentBackdropItemId')
                if parentId:
                    # If there is a parentId, go through the parent backdrop list
                    parentbackdrops = item['ParentBackdropImageTags']

                    for index, tag in enumerate(parentbackdrops):
                        artwork = (
                            "%s/emby/Items/%s/Images/Backdrop/%s?"
                            "MaxWidth=%s&MaxHeight=%s&Format=original&Tag=%s%s"
                            % (server, parentId, index, maxWidth, maxHeight, tag, customquery))
                        allartworks['Backdrop'].append(artwork)

            # Process the rest of the artwork
            parentartwork = ['Logo', 'Art', 'Thumb']
            for parentart in parentartwork:

                if not allartworks[parentart]:
                    
                    parentId = item.get('Parent%sItemId' % parentart)
                    if parentId:
                        
                        parentTag = item['Parent%sImageTag' % parentart]
                        artwork = (
                            "%s/emby/Items/%s/Images/%s/0?"
                            "MaxWidth=%s&MaxHeight=%s&Format=original&Tag=%s%s"
                            % (server, parentId, parentart,
                                maxWidth, maxHeight, parentTag, customquery))
                        allartworks[parentart] = artwork

            # Parent album works a bit differently
            if not allartworks['Primary']:

                parentId = item.get('AlbumId')
                if parentId and item.get('AlbumPrimaryImageTag'):
                    
                    parentTag = item['AlbumPrimaryImageTag']
                    artwork = (
                        "%s/emby/Items/%s/Images/Primary/0?"
                        "MaxWidth=%s&MaxHeight=%s&Format=original&Tag=%s%s"
                        % (server, parentId, maxWidth, maxHeight, parentTag, customquery))
                    allartworks['Primary'] = artwork

        return allartworks