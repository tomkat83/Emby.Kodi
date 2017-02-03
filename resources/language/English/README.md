# PlexKodiConnect (PKC)
**Combine the best frontend media player Kodi with the best multimedia backend server Plex**

PKC combines the best of Kodi - ultra smooth navigation, beautiful and highly customizable user interfaces and playback of any file under the sun - and the Plex Media Server.

Have a look at [some screenshots](https://github.com/croneter/PlexKodiConnect/wiki/Some-PKC-Screenshots) to see what's possible. 


### Content
* [**Warning**](https://github.com/croneter/PlexKodiConnect/tree/hotfixes#warning)
* [**What does PKC do and how is it different from the official 'Plex for Kodi'**](https://github.com/croneter/PlexKodiConnect/tree/hotfixes#what-does-pkc-do-and-how-is-it-different-from-the-official-plex-for-kod)
* [**Download and Installation**](https://github.com/croneter/PlexKodiConnect/tree/hotfixes#download-and-installation)
* [**Important notes**](https://github.com/croneter/PlexKodiConnect/tree/hotfixes#important-notes)
* [**Donations**](https://github.com/croneter/PlexKodiConnect/tree/hotfixes#donations)
* [**What is currently supported?**](https://github.com/croneter/PlexKodiConnect/tree/hotfixes#what-is-currently-supported)
* [**Known Larger Issues**](https://github.com/croneter/PlexKodiConnect/tree/hotfixes#known-larger-issues)
* [**Issues being worked on**](https://github.com/croneter/PlexKodiConnect/tree/hotfixes#issues-being-worked-on)
* [**Pipeline for future development**](https://github.com/croneter/PlexKodiConnect/tree/hotfixes#what-could-be-in-the-pipeline-for-future-development)
* [**Checkout the PKC Wiki**](https://github.com/croneter/PlexKodiConnect/tree/hotfixes#checkout-the-pkc-wiki)
* [**Credits**](https://github.com/croneter/PlexKodiConnect/tree/hotfixes#credits)

### Warning
Use at your own risk! This plugin assumes that you manage all your videos with Plex (and none with Kodi). You might lose data already stored in the Kodi video and music databases as this plugin directly changes them. Don't worry if you want Plex to manage all your media (like you should ;-)). 

### What does PKC do and how is it different from the official ['Plex for Kodi'](https://www.plex.tv/apps/computer/kodi/)?

With other Plex addons for Kodi such as the official [Plex for Kodi](https://www.plex.tv/apps/computer/kodi/) or [PlexBMC](https://forums.plex.tv/discussion/106593/plexbmc-xbmc-add-on-to-connect-to-plex-media-server) there are a couple of issues:
- Other Kodi addons such as NextAired, remote apps and others won't work
- You can only use special Kodi skins
- Slow speed: when browsing data has to be retrieved from the server. Especially on slower devices this can take too much time and you will notice artwork being loaded slowly while you browse the library
- All kinds of workarounds are needed to get the best experience on Kodi clients

PKC synchronizes your media from your Plex server to the native Kodi database. Because PKC uses the native Kodi database, the above limitations are gone! 
- Use any Kodi skin you want!
- You can browse your media at full speed, images are cached
- All other Kodi addons will be able to "see" your media, thinking it's normal Kodi stuff

Some people argue that PKC is 'hacky' because of the way it directly accesses the Kodi database. See [here for a more thorough discussion](https://github.com/croneter/PlexKodiConnect/wiki/Is-PKC-'hacky'%3F). 

### Download and Installation
[ ![Download](https://api.bintray.com/packages/croneter/PlexKodiConnect/PlexKodiConnect/images/download.svg) ](https://dl.bintray.com/croneter/PlexKodiConnect/bin/repository.plexkodiconnect/repository.plexkodiconnect-1.0.0.zip)

Install PKC via the PlexKodiConnect Kodi repository (we cannot use the official Kodi repository as PKC messes with Kodi's databases). See the [installation guideline on how to do this](https://github.com/croneter/PlexKodiConnect/wiki/Installation).

**Possibly UNSTABLE BETA version:** [ ![Download](https://api.bintray.com/packages/croneter/PlexKodiConnect_BETA/PlexKodiConnect_BETA/images/download.svg) ](https://dl.bintray.com/croneter/PlexKodiConnect_BETA/bin-BETA/repository.plexkodiconnectbeta/repository.plexkodiconnectbeta-1.0.0.zip)

### Important Notes

1. If you are using a **low CPU device like a Raspberry Pi or a CuBox**, PKC might be instable or crash during initial sync. Lower the number of threads in the [PKC settings under Sync Options](https://github.com/croneter/PlexKodiConnect/wiki/PKC-settings#sync-options): `Limit artwork cache threads: 5`
Don't forget to reboot Kodi after that.
2. **Compatibility**: 
    * PKC is currently not compatible with Kodi's Video Extras plugin. **Deactivate Video Extras** if trailers/movies start randomly playing. 
    * PKC is not (and will never be) compatible with the **MySQL database replacement** in Kodi. In fact, PKC replaces the MySQL functionality because it acts as a "man in the middle" for your entire media library.
    * If **another plugin is not working** like it's supposed to, try to use [PKC direct paths](https://github.com/croneter/PlexKodiConnect/wiki/Direct-Paths)
3. If you post logs, your **Plex tokens** might be included. Be sure to double and triple check for tokens before posting any logs anywhere by searching for `token`

### Donations
I'm not in any way affiliated with Plex. Thank you very much for a small donation via ko-fi.com and PayPal if you appreciate PKC.  
**Full disclaimer:** I will see your name and address on my PayPal account. Rest assured that I will not share this with anyone. 

[ ![Download](https://az743702.vo.msecnd.net/cdn/kofi1.png?v=a|alt=Buy Me a Coffee)](https://ko-fi.com/A8182EB)

### What is currently supported?

PKC currently provides the following features:
- All Plex library types
    + Movies and Home Videos
    + TV Shows
    + Music
    + Pictures and Photos
- Different PKC interface languages:
    + English
    + German
    + Czech (thanks @Pavuucek)
    + More coming up
- [Plex Watch Later / Plex It!](https://support.plex.tv/hc/en-us/sections/200211783-Plex-It-)
- [Plex Companion](https://support.plex.tv/hc/en-us/sections/200276908-Plex-Companion): fling Plex media (or anything else) from other Plex devices to PlexKodiConnect
- [Plex Transcoding](https://support.plex.tv/hc/en-us/articles/200250377-Transcoding-Media)
- Automatically download more artwork from [Fanart.tv](https://fanart.tv/), just like the Kodi addon [Artwork Downloader](http://kodi.wiki/view/Add-on:Artwork_Downloader)
    + Banners
    + Disc art
    + Clear logos
    + Landscapes
    + Clear art
    + Extra fanart backgrounds
- Automatically group movies into [movie sets](http://kodi.wiki/view/movie_sets)
- Direct play from network paths (e.g. "\\\\server\\Plex\\movie.mkv") instead of streaming from slow HTTP (e.g. "192.168.1.1:32400"). You have to setup all your Plex libraries to point to such network paths. Do have a look at [the wiki here](https://github.com/croneter/PlexKodiConnect/wiki/Direct-Paths)
- Delete PMS items from the Kodi context menu

### Known Larger Issues

Solutions are unlikely due to the nature of these issues
- A Plex Media Server "bug" leads to frequent and slow syncs, see [here for more info](https://github.com/croneter/PlexKodiConnect/issues/135)
- *Plex Music when using Addon paths instead of Native Direct Paths:* Kodi tries to scan every(!) single Plex song on startup. This leads to errors in the Kodi log file and potentially even crashes. See the [Github issue](https://github.com/croneter/PlexKodiConnect/issues/14) for more details
- *Plex Music when using Addon paths instead of Native Direct Paths:* You must have a static IP address for your Plex media server if you plan to use Plex Music features
- External Plex subtitles (in separate files, e.g. mymovie.srt) can be used, but it is impossible to label them correctly and tell what language they are in. However, this is not the case if you use direct paths

*Background Sync:*
The Plex Server does not tell anyone of the following changes. Hence PKC cannot detect these changes instantly but will notice them only on full/delta syncs (standard settings is every 60 minutes)
- Toggle the viewstate of an item to (un)watched outside of Kodi
- Changing details of an item, e.g. replacing a poster  

However, some changes to individual items are instantly detected, e.g. if you match a yet unrecognized movie. 


### Issues being worked on

Have a look at the [Github Issues Page](https://github.com/croneter/PlexKodiConnect/issues). Before you open your own issue, please read [How to report a bug](https://github.com/croneter/PlexKodiConnect/wiki/How-to-Report-A-Bug).


### What could be in the pipeline for future development?

- Plex channels
- Movie extras (trailers already work)
- Playlists
- Music Videos

### Checkout the PKC Wiki
The [Wiki can be found here](https://github.com/croneter/PlexKodiConnect/wiki) and will hopefully answer all your questions. You can even edit the wiki yourself!

### Credits

- PlexKodiConnect shamelessly uses pretty much all the code of "Emby for Kodi" by the awesome Emby team (see https://github.com/MediaBrowser/plugin.video.emby). Thanks for sharing guys!!
- Plex Companion ("PlexBMC Helper") and other stuff were adapted from @Hippojay 's great work (see https://github.com/hippojay).
- The foundation of the Plex API is all iBaa's work (https://github.com/iBaa/PlexConnect).
