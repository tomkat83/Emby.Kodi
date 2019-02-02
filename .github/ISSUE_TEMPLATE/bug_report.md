---
name: Bug report
about: Create a report to help us improve. Please read the instructions carefully.
title: ''
labels: ''
assignees: ''

---

## Help yourself
* I did try to restart Kodi :-)
* I checked the [PKC Frequently Asked Questions on the PKC wiki](https://github.com/croneter/PlexKodiConnect/wiki/faq)
* I did try to reset the Kodi database by going to `PKC Settings -> Advanced -> "Reset the database and optionally reset PlexKodiConnect"` and then hitting YES, NO
* I did check the [existing issues on Github](https://github.com/croneter/PlexKodiConnect/issues)

## Describe the bug
A clear and concise description of what the bug is.

## To Reproduce
Steps to reproduce the behavior:
1. Go to '...'
2. Click on '....'
3. Scroll down to '....'
4. See error

## Expected behavior
A clear and concise description of what you expected to happen.

## You need to attach a KODI LOG FILE!
A Kodi **DEBUG** log file is needed that you recorded while you reproduced the bug. **Do clean your log of all Plex tokens (="Plex passwords")!!!** .
1. Activate Kodi's debug logging by going to the Kodi `Settings` -> `System` -> `Logging`. Then toggle the `Enable debug logging` setting.
2. Restart Kodi to start with a "fresh" log file.
3. Reproduce the bug.
4. Follow the [Kodi instructions](http://kodi.wiki/view/Log_file/Easy) to grab/share the Kodi log file. Usually only `kodi.log` is needed
    * You can [find the log file here](http://kodi.wiki/view/Log_file/Advanced#Location)
5. **Delete all references to any of your Plex tokens** by searching for `X-Plex-Token` and `accesstoken` and replacing the strings just after that!
    * It's easiest if you copy your token, then use Search&Replace for the entire log file
    * You don't want others to have access to your Plex installation....
6. Drop your log file here in this issue. Or use a free pasting-service like https://pastebin.com and include the link to it here
