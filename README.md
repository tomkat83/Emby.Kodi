[![stable version](https://img.shields.io/badge/stable_version-2.3.0-blue.svg?maxAge=60&style=flat) ](https://github.com/croneter/binary_repo/raw/master/stable/repository.plexkodiconnect/repository.plexkodiconnect-1.0.2.zip) 
[![beta version](https://img.shields.io/badge/beta_version-2.3.0-red.svg?maxAge=60&style=flat) ](https://github.com/croneter/binary_repo/raw/master/beta/repository.plexkodiconnectbeta/repository.plexkodiconnectbeta-1.0.2.zip)

[![Installation](https://img.shields.io/badge/wiki-installation-brightgreen.svg?maxAge=60&style=flat)](https://github.com/croneter/PlexKodiConnect/wiki/Installation)
[![FAQ](https://img.shields.io/badge/wiki-FAQ-brightgreen.svg?maxAge=60&style=flat)](https://github.com/croneter/PlexKodiConnect/wiki/faq)
[![Forum](https://img.shields.io/badge/forum-plex-orange.svg?maxAge=60&style=flat)](https://forums.plex.tv/discussion/210023/plexkodiconnect-let-kodi-talk-to-your-plex)

[![GitHub issues](https://img.shields.io/github/issues/croneter/PlexKodiConnect.svg?maxAge=60&style=flat)](https://github.com/croneter/PlexKodiConnect/issues) [![GitHub pull requests](https://img.shields.io/github/issues-pr/croneter/PlexKodiConnect.svg?maxAge=60&style=flat)](https://github.com/croneter/PlexKodiConnect/pulls) [![Codacy Badge](https://api.codacy.com/project/badge/Grade/a66870f19ced4fb98f94d9fd56e34e87)](https://www.codacy.com/app/croneter/PlexKodiConnect?utm_source=github.com&amp;utm_medium=referral&amp;utm_content=croneter/PlexKodiConnect&amp;utm_campaign=Badge_Grade)


# PlexKodiConnect (PKC)
**Combine the best frontend media player Kodi with the best multimedia backend server Plex**

PKC combines the best of Kodi - ultra smooth navigation, beautiful and highly customizable user interfaces and playback of any file under the sun - and the Plex Media Server.

Have a look at [some screenshots](https://github.com/croneter/PlexKodiConnect/wiki/Some-PKC-Screenshots) to see what's possible. 

### Update Your PKC Repo to Receive Updates!

Unfortunately, the PKC Kodi repository had to move because it stopped working (thanks https://bintray.com). If you installed PKC before December 15, 2017, you need to [**MANUALLY** update the repo once](https://github.com/croneter/PlexKodiConnect/wiki/Update-PKC-Repository).

### Content
* [**Download and Installation**](#download-and-installation)
* [**What does PKC do?**](#what-does-pkc-do)
* [**Warning**](#warning)
* [**PKC Features**](#pkc-features)
* [**Additional Artwork**](#additional-artwork)
* [**Donations**](#donations)
* [**Request a New Feature**](#request-a-new-feature)
* [**Issues and Bugs**](#issues-and-bugs)
* [**Credits**](#credits)

### Download and Installation

Install PKC via the PlexKodiConnect Kodi repository download button just below (do NOT use the standard GitHub download!). See the [github wiki installation manual](https://github.com/croneter/PlexKodiConnect/wiki/Installation) for a detailed guide. Please use the stable version except if you really know what you're doing. Kodi will update PKC automatically. 

| Stable version | Beta version |
|----------------|--------------|
| [![stable version](https://img.shields.io/badge/stable_version-latest-blue.svg?maxAge=60&style=flat) ](https://github.com/croneter/binary_repo/raw/master/stable/repository.plexkodiconnect/repository.plexkodiconnect-1.0.2.zip)  | [![beta version](https://img.shields.io/badge/beta_version-latest-red.svg?maxAge=60&style=flat) ](https://github.com/croneter/binary_repo/raw/master/beta/repository.plexkodiconnectbeta/repository.plexkodiconnectbeta-1.0.2.zip) |

### What does PKC do?
PKC synchronizes your media from your Plex server to the native Kodi database. Hence:
- Use virtually any other Kodi add-on
- Use any Kodi skin, completely customize Kodi's look
- Browse your media at full speed (cached artwork)
- Automatically get additional artwork (more than Plex offers)
- Enjoy Plex features using the Kodi interface

### Warning
Use at your own risk! This plugin assumes that you manage all your videos with Plex (and none with Kodi). You might lose data already stored in the Kodi video and music databases as this plugin directly changes them. Don't worry if you want Plex to manage all your media (like you should ;-)). 

Some people argue that PKC is 'hacky' because of the way it directly accesses the Kodi database. See [here for a more thorough discussion](https://github.com/croneter/PlexKodiConnect/wiki/Is-PKC-'hacky'%3F). 

### PKC Features

- Support for Kodi 18 Leia Alpha 2 (nightly versions are NOT supported!)
- Support for Kodi 17 Krypton
- [Amazon Alexa voice recognition](https://www.plex.tv/apps/streaming-devices/amazon-alexa)
- [Cinema Trailers & Extras](https://support.plex.tv/articles/202934883-cinema-trailers-extras/)
- [Plex Watch Later / Plex It!](https://support.plex.tv/hc/en-us/sections/200211783-Plex-It-)
- [Plex Companion](https://support.plex.tv/hc/en-us/sections/200276908-Plex-Companion): fling Plex media (or anything else) from other Plex devices to PlexKodiConnect
- [Plex Transcoding](https://support.plex.tv/hc/en-us/articles/200250377-Transcoding-Media)
- Automatically download more artwork from [Fanart.tv](https://fanart.tv/), just like the Kodi addon [Artwork Downloader](http://kodi.wiki/view/Add-on:Artwork_Downloader)
- Automatically group movies into [movie sets](http://kodi.wiki/view/movie_sets)
- [Direct play](https://github.com/croneter/PlexKodiConnect/wiki/Direct-Play) from network paths (e.g. "\\\\server\\Plex\\movie.mkv"), something unique to PKC
- Delete PMS items from the Kodi context menu
- PKC is available in the following languages:
    + English
    + German
    + Czech, thanks @Pavuucek
    + Spanish, thanks @bartolomesoriano, @danichispa 
    + Danish, thanks @FIGHT
    + Italian, thanks @nikkux, @chicco83
    + Dutch, thanks @mvanbaak
    + French, thanks @lflforce, @ahivert, @Nox71, @CotzaDev, @vinch100, @Polymorph31, @jbnitro, @Elixir59 
    + Chinese Traditional, thanks @old2tan
    + Chinese Simplified, thanks @everdream
    + Norwegian, thanks @mjorud
    + Portuguese, thanks @goncalo532 
    + Russian, thanks @UncleStark
    + Hungarian, thanks @savage93
    + Ukrainian, thanks @uniss
    + [Please help and easily translate PKC!](https://www.transifex.com/croneter/pkc)

### Additional Artwork
PKC uses additional artwork for free from [TheMovieDB](https://www.themoviedb.org). Many thanks for lettings us use the API, guys!
[![Logo of TheMovieDB](themoviedb.png)](https://www.themoviedb.org)

### Donations
I'm not in any way affiliated with Plex. Thank you very much for a small donation via ko-fi.com and PayPal, Bitcoin or Ether if you appreciate PKC.  
**Full disclaimer:** I will see your name and address if you use PayPal. Rest assured that I will not share this with anyone. 

[![Donations](https://az743702.vo.msecnd.net/cdn/kofi1.png?v=a)](https://ko-fi.com/A8182EB)
    
**Ethereum address for donations:    
0x0f57D98E08e617292D8bC0B3448dd79BF4Cf8e7F**

**Bitcoin address for donations:    
3BhwvUsqAGtAZodGUx4mTP7pTECjf1AejT**


### Request a New Feature

[![Feature Requests](http://feathub.com/croneter/PlexKodiConnect?format=svg)](http://feathub.com/croneter/PlexKodiConnect)

### Issues and Bugs

Have a look at the [Github Issues Page](https://github.com/croneter/PlexKodiConnect/issues). Before you open your own issue, please read [How to report a bug](https://github.com/croneter/PlexKodiConnect/wiki/How-to-Report-A-Bug).


### Credits

- PlexKodiConnect shamelessly uses pretty much all the code of "Emby for Kodi" by the awesome Emby team (see https://github.com/MediaBrowser/plugin.video.emby). Thanks for sharing guys!!
- Plex Companion ("PlexBMC Helper") and other stuff were adapted from @Hippojay 's great work (see https://github.com/hippojay).
- The foundation of the Plex API is all iBaa's work (https://github.com/iBaa/PlexConnect).
