#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
import re
from os import path
import xml.etree.ElementTree as etree

from . import app
from . import path_ops
from . import variables as v
from .exceptions import SubtitleError

LOG = getLogger('PLEX.subtitles')

# See https://kodi.wiki/view/Subtitles
SUBTITLE_LANGUAGE = re.compile(r'''(?i)[\. -]*(.*?)([\. -]forced)?$''')

# Plex support for external subtitles: srt, smi, ssa, aas, vtt
# https://support.plex.tv/articles/200471133-adding-local-subtitles-to-your-media/

# Which subtitles files are picked up by Kodi, what extensions do they need?
KODI_SUBTITLE_EXTENSIONS = ('srt', 'ssa', 'ass', 'usf', 'cdg', 'idx', 'sub',
                            'utf', 'aqt', 'jss', 'psb', 'rt', 'smi', 'txt',
                            'smil', 'stl', 'dks', 'pjs', 'mpl2', 'mks')

# Official language designations. Tuples consist of
#    (ISO language name, ISO 639-1, ISO 639-2, ISO 639-2/B)
# source: https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes
LANGUAGE_ISO_CODES = (
    ('abkhazian', 'ab', 'abk', 'abk'),
    ('afar', 'aa', 'aar', 'aar'),
    ('afrikaans', 'af', 'afr', 'afr'),
    ('akan', 'ak', 'aka', 'aka'),
    ('albanian', 'sq', 'sqi', 'alb'),
    ('amharic', 'am', 'amh', 'amh'),
    ('arabic', 'ar', 'ara', 'ara'),
    ('aragonese', 'an', 'arg', 'arg'),
    ('armenian', 'hy', 'hye', 'arm'),
    ('assamese', 'as', 'asm', 'asm'),
    ('avaric', 'av', 'ava', 'ava'),
    ('avestan', 'ae', 'ave', 'ave'),
    ('aymara', 'ay', 'aym', 'aym'),
    ('azerbaijani', 'az', 'aze', 'aze'),
    ('bambara', 'bm', 'bam', 'bam'),
    ('bashkir', 'ba', 'bak', 'bak'),
    ('basque', 'eu', 'eus', 'baq'),
    ('belarusian', 'be', 'bel', 'bel'),
    ('bengali', 'bn', 'ben', 'ben'),
    ('bislama', 'bi', 'bis', 'bis'),
    ('bosnian', 'bs', 'bos', 'bos'),
    ('breton', 'br', 'bre', 'bre'),
    ('bulgarian', 'bg', 'bul', 'bul'),
    ('burmese', 'my', 'mya', 'bur'),
    ('catalan', 'ca', 'cat', 'cat'),
    ('chamorro', 'ch', 'cha', 'cha'),
    ('chechen', 'ce', 'che', 'che'),
    ('chichewa', 'ny', 'nya', 'nya'),
    ('chinese', 'zh', 'zho', 'chi'),
    ('chuvash', 'cv', 'chv', 'chv'),
    ('cornish', 'kw', 'cor', 'cor'),
    ('corsican', 'co', 'cos', 'cos'),
    ('cree', 'cr', 'cre', 'cre'),
    ('croatian', 'hr', 'hrv', 'hrv'),
    ('czech', 'cs', 'ces', 'cze'),
    ('danish', 'da', 'dan', 'dan'),
    ('divehi', 'dv', 'div', 'div'),
    ('dutch', 'nl', 'nld', 'dut'),
    ('dzongkha', 'dz', 'dzo', 'dzo'),
    ('english', 'en', 'eng', 'eng'),
    ('esperanto', 'eo', 'epo', 'epo'),
    ('estonian', 'et', 'est', 'est'),
    ('ewe', 'ee', 'ewe', 'ewe'),
    ('faroese', 'fo', 'fao', 'fao'),
    ('fijian', 'fj', 'fij', 'fij'),
    ('finnish', 'fi', 'fin', 'fin'),
    ('french', 'fr', 'fra', 'fre'),
    ('fulah', 'ff', 'ful', 'ful'),
    ('galician', 'gl', 'glg', 'glg'),
    ('georgian', 'ka', 'kat', 'geo'),
    ('german', 'de', 'deu', 'ger'),
    ('greek', 'el', 'ell', 'gre'),
    ('guarani', 'gn', 'grn', 'grn'),
    ('gujarati', 'gu', 'guj', 'guj'),
    ('haitian', 'ht', 'hat', 'hat'),
    ('hausa', 'ha', 'hau', 'hau'),
    ('hebrew', 'he', 'heb', 'heb'),
    ('herero', 'hz', 'her', 'her'),
    ('hindi', 'hi', 'hin', 'hin'),
    ('hiri motu', 'ho', 'hmo', 'hmo'),
    ('hungarian', 'hu', 'hun', 'hun'),
    ('interlingua', 'ia', 'ina', 'ina'),
    ('indonesian', 'id', 'ind', 'ind'),
    ('interlingue', 'ie', 'ile', 'ile'),
    ('irish', 'ga', 'gle', 'gle'),
    ('igbo', 'ig', 'ibo', 'ibo'),
    ('inupiaq', 'ik', 'ipk', 'ipk'),
    ('ido', 'io', 'ido', 'ido'),
    ('icelandic', 'is', 'isl', 'ice'),
    ('italian', 'it', 'ita', 'ita'),
    ('inuktitut', 'iu', 'iku', 'iku'),
    ('japanese', 'ja', 'jpn', 'jpn'),
    ('javanese', 'jv', 'jav', 'jav'),
    ('kalaallisut', 'kl', 'kal', 'kal'),
    ('kannada', 'kn', 'kan', 'kan'),
    ('kanuri', 'kr', 'kau', 'kau'),
    ('kashmiri', 'ks', 'kas', 'kas'),
    ('kazakh', 'kk', 'kaz', 'kaz'),
    ('central khmer', 'km', 'khm', 'khm'),
    ('kikuyu', 'ki', 'kik', 'kik'),
    ('kinyarwanda', 'rw', 'kin', 'kin'),
    ('kirghiz', 'ky', 'kir', 'kir'),
    ('komi', 'kv', 'kom', 'kom'),
    ('kongo', 'kg', 'kon', 'kon'),
    ('korean', 'ko', 'kor', 'kor'),
    ('kurdish', 'ku', 'kur', 'kur'),
    ('kuanyama', 'kj', 'kua', 'kua'),
    ('latin', 'la', 'lat', 'lat'),
    ('luxembourgish', 'lb', 'ltz', 'ltz'),
    ('ganda', 'lg', 'lug', 'lug'),
    ('limburgan', 'li', 'lim', 'lim'),
    ('lingala', 'ln', 'lin', 'lin'),
    ('lao', 'lo', 'lao', 'lao'),
    ('lithuanian', 'lt', 'lit', 'lit'),
    ('luba-katanga', 'lu', 'lub', 'lub'),
    ('latvian', 'lv', 'lav', 'lav'),
    ('manx', 'gv', 'glv', 'glv'),
    ('macedonian', 'mk', 'mkd', 'mac'),
    ('malagasy', 'mg', 'mlg', 'mlg'),
    ('malay', 'ms', 'msa', 'may'),
    ('malayalam', 'ml', 'mal', 'mal'),
    ('maltese', 'mt', 'mlt', 'mlt'),
    ('maori', 'mi', 'mri', 'mao'),
    ('marathi', 'mr', 'mar', 'mar'),
    ('marshallese', 'mh', 'mah', 'mah'),
    ('mongolian', 'mn', 'mon', 'mon'),
    ('nauru', 'na', 'nau', 'nau'),
    ('navajo', 'nv', 'nav', 'nav'),
    ('north ndebele', 'nd', 'nde', 'nde'),
    ('nepali', 'ne', 'nep', 'nep'),
    ('ndonga', 'ng', 'ndo', 'ndo'),
    ('norwegian bokmål', 'nb', 'nob', 'nob'),
    ('norwegian nynorsk', 'nn', 'nno', 'nno'),
    ('norwegian', 'no', 'nor', 'nor'),
    ('sichuan yi', 'ii', 'iii', 'iii'),
    ('south ndebele', 'nr', 'nbl', 'nbl'),
    ('occitan', 'oc', 'oci', 'oci'),
    ('ojibwa', 'oj', 'oji', 'oji'),
    ('church slavic', 'cu', 'chu', 'chu'),
    ('oromo', 'om', 'orm', 'orm'),
    ('oriya', 'or', 'ori', 'ori'),
    ('ossetian', 'os', 'oss', 'oss'),
    ('punjabi', 'pa', 'pan', 'pan'),
    ('pali', 'pi', 'pli', 'pli'),
    ('persian', 'fa', 'fas', 'per'),
    ('polish', 'pl', 'pol', 'pol'),
    ('pashto', 'ps', 'pus', 'pus'),
    ('portuguese', 'pt', 'por', 'por'),
    ('quechua', 'qu', 'que', 'que'),
    ('romansh', 'rm', 'roh', 'roh'),
    ('rundi', 'rn', 'run', 'run'),
    ('romanian', 'ro', 'ron', 'rum'),
    ('russian', 'ru', 'rus', 'rus'),
    ('sanskrit', 'sa', 'san', 'san'),
    ('sardinian', 'sc', 'srd', 'srd'),
    ('sindhi', 'sd', 'snd', 'snd'),
    ('northern sami', 'se', 'sme', 'sme'),
    ('samoan', 'sm', 'smo', 'smo'),
    ('sango', 'sg', 'sag', 'sag'),
    ('serbian', 'sr', 'srp', 'srp'),
    ('gaelic', 'gd', 'gla', 'gla'),
    ('shona', 'sn', 'sna', 'sna'),
    ('sinhala', 'si', 'sin', 'sin'),
    ('slovak', 'sk', 'slk', 'slo'),
    ('slovenian', 'sl', 'slv', 'slv'),
    ('somali', 'so', 'som', 'som'),
    ('southern sotho', 'st', 'sot', 'sot'),
    ('spanish', 'es', 'spa', 'spa'),
    ('sundanese', 'su', 'sun', 'sun'),
    ('swahili', 'sw', 'swa', 'swa'),
    ('swati', 'ss', 'ssw', 'ssw'),
    ('swedish', 'sv', 'swe', 'swe'),
    ('tamil', 'ta', 'tam', 'tam'),
    ('telugu', 'te', 'tel', 'tel'),
    ('tajik', 'tg', 'tgk', 'tgk'),
    ('thai', 'th', 'tha', 'tha'),
    ('tigrinya', 'ti', 'tir', 'tir'),
    ('tibetan', 'bo', 'bod', 'tib'),
    ('turkmen', 'tk', 'tuk', 'tuk'),
    ('tagalog', 'tl', 'tgl', 'tgl'),
    ('tswana', 'tn', 'tsn', 'tsn'),
    ('tonga', 'to', 'ton', 'ton'),
    ('turkish', 'tr', 'tur', 'tur'),
    ('tsonga', 'ts', 'tso', 'tso'),
    ('tatar', 'tt', 'tat', 'tat'),
    ('twi', 'tw', 'twi', 'twi'),
    ('tahitian', 'ty', 'tah', 'tah'),
    ('uighur', 'ug', 'uig', 'uig'),
    ('ukrainian', 'uk', 'ukr', 'ukr'),
    ('urdu', 'ur', 'urd', 'urd'),
    ('uzbek', 'uz', 'uzb', 'uzb'),
    ('venda', 've', 'ven', 'ven'),
    ('vietnamese', 'vi', 'vie', 'vie'),
    ('volapük', 'vo', 'vol', 'vol'),
    ('walloon', 'wa', 'wln', 'wln'),
    ('welsh', 'cy', 'cym', 'wel'),
    ('wolof', 'wo', 'wol', 'wol'),
    ('western frisian', 'fy', 'fry', 'fry'),
    ('xhosa', 'xh', 'xho', 'xho'),
    ('yiddish', 'yi', 'yid', 'yid'),
    ('yoruba', 'yo', 'yor', 'yor'),
    ('zhuang', 'za', 'zha', 'zha'),
    ('zulu', 'zu', 'zul', 'zul'),
)


def accessible_plex_subtitles(playmethod, playing_file, xml_streams):
    if playmethod not in (v.PLAYBACK_METHOD_DIRECT_PATH,
                          v.PLAYBACK_METHOD_DIRECT_PLAY):
        # We can access all subtitles because we're downloading additional
        # external ones into the Kodi PKC add-on directory
        streams = []
        # Kodi ennumerates EXTERNAL subtitles first, then internal ones
        for stream in xml_streams:
            if stream.get('streamType') == '3' and 'key' in stream.attrib:
                streams.append(stream)
        for stream in xml_streams:
            if stream.get('streamType') == '3' and 'key' not in stream.attrib:
                streams.append(stream)
        if streams:
            LOG.debug('Working with the following Plex subtitle streams:')
            log_plex_streams(streams)
        return streams
    kodi_subs = kodi_subs_from_player()
    plex_streams_int, plex_streams_ext = accessible_plex_sub_streams(xml_streams)
    # Kodi appends internal streams at the end of its list
    kodi_subs_ext = kodi_subs[:len(kodi_subs) - len(plex_streams_int)]
    LOG.debug('Kodi list of external subs: %s', kodi_subs_ext)
    LOG.debug('Kodi has %s external subs, Plex %s, trying to match them',
              len(kodi_subs_ext), len(plex_streams_ext))
    dirname, basename = path.split(playing_file)
    filename, _ = path.splitext(basename)
    try:
        kodi_subs_file = kodi_external_subs(dirname, filename, kodi_subs_ext)
        reordered_plex_streams_ext = reorder_plex_streams(plex_streams_ext,
                                                          kodi_subs_file)
    except SubtitleError:
        # Add dummy subtitles so we won't match against Plex subtitles that
        # are in an incorrect order - keeps Kodi order of subs intact
        reordered_plex_streams_ext = [DummySub()
                                      for _ in range(len(kodi_subs_ext))]
    reordered_plex_streams_ext.extend(plex_streams_int)
    return reordered_plex_streams_ext


def reorder_plex_streams(plex_streams_ext, kodi_subs_file):
    """
    Returns the Plex streams in a "best-guess" order as indicated by the
    Kodi external subtitles kodi_subs_file
    """
    order = [None for i in range(len(kodi_subs_file))]
    # Pick subtitles with known language, extension and "forced" True first
    for i, kodi_sub in enumerate(kodi_subs_file):
        if not kodi_sub['iso'] or not kodi_sub['forced']:
            continue
        for plex_stream in plex_streams_ext:
            if not plex_stream.get('forced'):
                continue
            elif not kodi_sub['iso'][1] == plex_stream.get('languageTag'):
                continue
            elif not kodi_sub['codec'] == plex_stream.get('codec').lower():
                continue
            # Pick the first matching result - even though it's a best guess
            order[i] = plex_stream
            plex_streams_ext.remove(plex_stream)
            break
    # Pick non-forced
    for i, kodi_sub in enumerate(kodi_subs_file):
        if order[i] is not None or not kodi_sub['iso']:
            continue
        for plex_stream in plex_streams_ext:
            if not kodi_sub['iso'][1] == plex_stream.get('languageTag'):
                continue
            elif not kodi_sub['codec'] == plex_stream.get('codec').lower():
                continue
            elif not (kodi_sub['forced'] is (plex_stream.get('forced') == '1')):
                continue
            # Pick the first matching result - even though it's a best guess
            order[i] = plex_stream
            plex_streams_ext.remove(plex_stream)
            break
    # Pick subs irrelevant of forced flag
    for i, kodi_sub in enumerate(kodi_subs_file):
        if order[i] is not None or not kodi_sub['iso']:
            continue
        for plex_stream in plex_streams_ext:
            if not kodi_sub['iso'][1] == plex_stream.get('languageTag'):
                continue
            elif not kodi_sub['codec'] == plex_stream.get('codec').lower():
                continue
            # Pick the first matching result - even though it's a best guess
            order[i] = plex_stream
            plex_streams_ext.remove(plex_stream)
            break
    # Pick subs based on codec (Plex does not detect "English" as en). Forced
    # ones first
    for i, kodi_sub in enumerate(kodi_subs_file):
        if order[i] is not None or not kodi_sub['forced']:
            continue
        for plex_stream in plex_streams_ext:
            if not kodi_sub['codec'] == plex_stream.get('codec').lower():
                continue
            elif not plex_stream.get('forced'):
                continue
            elif plex_stream.get('languageTag') and kodi_sub['iso'] \
                    and not plex_stream.get('languageTag') == kodi_sub['iso'][1]:
                continue
            # Pick the first matching result - even though it's a best guess
            order[i] = plex_stream
            plex_streams_ext.remove(plex_stream)
            break
    # Pick subs based on codec alone (Plex does not detect "English" as en).
    # Non-forced
    for i, kodi_sub in enumerate(kodi_subs_file):
        if order[i] is not None:
            continue
        for plex_stream in plex_streams_ext:
            if not kodi_sub['codec'] == plex_stream.get('codec').lower():
                continue
            elif not (kodi_sub['forced'] is (plex_stream.get('forced') == '1')):
                continue
            elif plex_stream.get('languageTag') and kodi_sub['iso'] \
                    and not plex_stream.get('languageTag') == kodi_sub['iso'][1]:
                continue
            # Pick the first matching result - even though it's a best guess
            order[i] = plex_stream
            plex_streams_ext.remove(plex_stream)
            break
    # Pick subs based on codec alone (Plex does not detect "English" as en).
    # Even with miss-matching forced flag
    for i, kodi_sub in enumerate(kodi_subs_file):
        if order[i] is not None:
            continue
        for plex_stream in plex_streams_ext:
            if not kodi_sub['codec'] == plex_stream.get('codec').lower():
                continue
            elif plex_stream.get('languageTag') and kodi_sub['iso'] \
                    and not plex_stream.get('languageTag') == kodi_sub['iso'][1]:
                continue
            # Pick the first matching result - even though it's a best guess
            order[i] = plex_stream
            plex_streams_ext.remove(plex_stream)
            break
    # Now lets add dummies for Kodi subs we could not match
    for i, kodi_sub in enumerate(kodi_subs_file):
        if order[i] is not None:
            continue
        LOG.debug('Could not match Kodi sub number %s %s, adding a dummy',
                  i, kodi_sub)
        order[i] = DummySub()
    if plex_streams_ext:
        LOG.debug('We could not match the following Plex subtitles:')
        log_plex_streams(plex_streams_ext)
    if order:
        LOG.debug('Derived order of external subtitle streams:')
        log_plex_streams(order)
    return order


def log_plex_streams(plex_streams):
    for i, stream in enumerate(plex_streams):
        LOG.debug('Number %s: %s: %s', i, stream.tag, stream.attrib)


def accessible_plex_sub_streams(xml):
    # Any additionally downloaded subtitles are not accessible for Kodi
    # We're identifying them by the additional key 'providerTitle'
    plex_streams = [stream for stream in xml
                    if stream.get('streamType') == '3'
                    and not stream.get('providerTitle')]
    LOG.debug('Available Plex subtitle streams for currently playing item:')
    log_plex_streams(plex_streams)
    # Kodi can display internal subtitle streams for sure
    plex_streams_int = [x for x in plex_streams if 'key' not in x.attrib]
    # We need to check external ones
    # If the movie name is 'The Dark Knight (2008).mkv', Kodi finds
    # subtitles 'The Dark Knight (2008)*.*.<ext>'
    plex_streams_ext = [x for x in plex_streams if 'key' in x.attrib]
    return plex_streams_int, plex_streams_ext


def kodi_subs_from_player():
    """
    Kodi can only play subtitles that it pickes up itself: They lie in the
    same folder as the video file and are named similarly
    """
    kodi_subs = app.APP.player.getAvailableSubtitleStreams()
    LOG.debug('Kodi list of available subtitles: %s', kodi_subs)
    return kodi_subs


def kodi_external_subs(dirname, filename, kodi_subs_ext):
    file_subs = external_subs_from_filesystem(dirname, filename)
    if len(file_subs) != len(kodi_subs_ext):
        LOG.warn('Unexpected missmatch of number of Kodi subtitles')
        LOG.warn('Kodi subs: %s', kodi_subs_ext)
        LOG.warn('Subs from the filesystem: %s', file_subs)
        raise SubtitleError()
    for i, sub in enumerate(file_subs):
        if sub['iso'] and kodi_subs_ext[i].lower() not in sub['iso']:
            LOG.warn('Unexpected Kodi external subtitle language combo')
            LOG.warn('Kodi subs: %s', kodi_subs_ext)
            LOG.warn('Subs from the filesystem: %s', file_subs)
            raise SubtitleError()
    return file_subs


def external_subs_from_filesystem(dirname, filename):
    """
    Returns a list of dicts of subtitles lying within the directory dirname:
        {'iso': tuple of detected ISO language (see LANGUAGE_ISO_CODES) or None,
         'language': language string that Kodi might show in its GUI,
         'forced': has '[. -]forced' been appended to the filename?
         'file': subtitle file name}
    Supply with the currently playing filename as Kodi uses that to search
    for subtitles. See https://kodi.wiki/view/Subtitles
    """
    file_subs = []
    for root, dirs, files in path_ops.walk(dirname):
        for file in files:
            name, extension = path.splitext(file)
            # Get rid of the dot and force lowercase
            extension = extension[1:].lower()
            if extension not in KODI_SUBTITLE_EXTENSIONS:
                # Not an extension Kodi supports
                continue
            elif not name.startswith(filename):
                # Naming not up to standards, Kodi won't pick up this file
                # (but Plex might!!)
                continue
            regex = SUBTITLE_LANGUAGE.search(name.replace(filename, '', 1))
            language = (regex[1] or '').lower()
            forced = True if regex[2] else False
            iso = None
            if len(language) == 2:
                language_searchgrid = (1, )
            elif len(language) == 3:
                language_searchgrid = (2, 3)
            else:
                language_searchgrid = (0, )
            for lang in LANGUAGE_ISO_CODES:
                for i in language_searchgrid:
                    if lang[i] == language:
                        iso = lang
                        break
                else:
                    continue
                break
            file_subs.append({'iso': iso,
                              'language': language,
                              'forced': forced,
                              'codec': extension,
                              'file': '%s.%s' % (name, extension)})
    LOG.debug('Detected these external subtitles while scanning the file '
              'system: %s', file_subs)
    return file_subs


class DummySub(etree.Element):
    def __init__(self):
        super(DummySub, self).__init__('Stream-subtitle-dummy')
