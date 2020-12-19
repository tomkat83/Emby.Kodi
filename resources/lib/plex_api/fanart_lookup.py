#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
from re import sub
from string import punctuation

from ..downloadutils import DownloadUtils as DU
from .. import utils, variables as v

LOG = getLogger('PLEX.api.fanartlookup')

API_KEY = utils.settings('themoviedbAPIKey')

# How far apart can a video's airing date be (in years)
YEARS_APART = 1
# levenshtein_distance_ratio() returns a value between 0 (no match) and 1 (full
# match). What's the threshold?
LEVENSHTEIN_RATIO_THRESHOLD = 0.95
# Which character should we ignore when matching video titles?
EXCLUDE_CHARS = set(punctuation)


def external_item_id(title, year, plex_type, collection):
    LOG.debug('Start identifying %s (%s, %s)', title, year, plex_type)
    year = int(year) if year else None
    media_type = 'tv' if plex_type == v.PLEX_TYPE_SHOW else plex_type
    # if the title has the year in remove it as tmdb cannot deal with it...
    # replace e.g. 'The Americans (2015)' with 'The Americans'
    title = sub(r'\s*\(\d{4}\)$', '', title, count=1)
    url = 'https://api.themoviedb.org/3/search/%s' % media_type
    parameters = {
        'api_key': API_KEY,
        'language': v.KODILANGUAGE,
        'query': title
    }
    data = DU().downloadUrl(url,
                            authenticate=False,
                            parameters=parameters,
                            timeout=7)
    try:
        data = data['results']
    except (AttributeError, KeyError, TypeError):
        LOG.debug('No match found on themoviedb for %s (%s, %s)',
                  title, year, media_type)
        return
    LOG.debug('themoviedb returned results: %s', data)
    # Some entries don't contain a title or id - get rid of them
    data = [x for x in data if 'title' in x and 'id' in x]
    # Get rid of all results that do NOT have a matching release year
    if year:
        data = [x for x in data if __year_almost_matches(year, x)]
    if not data:
        LOG.debug('Empty results returned by themoviedb for %s (%s, %s)',
                  title, year, media_type)
        return
    # Calculate how similar the titles are
    title = sanitize_string(title)
    for entry in data:
        entry['match_score'] = levenshtein_distance_ratio(
            sanitize_string(entry['title']), title)
    # (one of the possibly many) best match using levenshtein distance ratio
    entry = max(data, key=lambda x: x['match_score'])
    if entry['match_score'] < LEVENSHTEIN_RATIO_THRESHOLD:
        LOG.debug('Best themoviedb match not good enough: %s', entry)
        return

    # Check if we got several matches. If so, take the most popular one
    best_matches = [x for x in data if
                    x['match_score'] == entry['match_score'] 
                    and 'popularity' in x]
    entry = max(best_matches, key=lambda x: x['popularity'])
    LOG.debug('Found themoviedb match: %s', entry)

    # lookup external tmdb_id and perform artwork lookup on fanart.tv
    tmdb_id = entry.get('id')
    parameters = {'api_key': API_KEY}
    if media_type == 'movie':
        url = 'https://api.themoviedb.org/3/movie/%s' % tmdb_id
        parameters['append_to_response'] = 'videos'
    elif media_type == 'tv':
        url = 'https://api.themoviedb.org/3/tv/%s' % tmdb_id
        parameters['append_to_response'] = 'external_ids,videos'
    media_id, poster, background = None, None, None
    for language in (v.KODILANGUAGE, 'en'):
        parameters['language'] = language
        data = DU().downloadUrl(url,
                                authenticate=False,
                                parameters=parameters,
                                timeout=7)
        try:
            data.get('test')
        except AttributeError:
            LOG.warning('Could not download %s with parameters %s',
                        url, parameters)
            continue
        if collection is False:
            if data.get('imdb_id'):
                media_id = str(data.get('imdb_id'))
                break
            if (data.get('external_ids') and
                    data['external_ids'].get('tvdb_id')):
                media_id = str(data['external_ids']['tvdb_id'])
                break
        else:
            if not data.get('belongs_to_collection'):
                continue
            media_id = data.get('belongs_to_collection').get('id')
            if not media_id:
                continue
            media_id = str(media_id)
            LOG.debug('Retrieved collections tmdb id %s for %s',
                      media_id, title)
            url = 'https://api.themoviedb.org/3/collection/%s' % media_id
            data = DU().downloadUrl(url,
                                    authenticate=False,
                                    parameters=parameters,
                                    timeout=7)
            try:
                data.get('poster_path')
            except AttributeError:
                LOG.debug('Could not find TheMovieDB poster paths for %s'
                          ' in the language %s', title, language)
                continue
            if not poster and data.get('poster_path'):
                poster = ('https://image.tmdb.org/t/p/original%s' %
                          data.get('poster_path'))
            if not background and data.get('backdrop_path'):
                background = ('https://image.tmdb.org/t/p/original%s' %
                              data.get('backdrop_path'))
    return media_id, poster, background


def __year_almost_matches(year, entry):
    try:
        entry_year = int(entry['release_date'][0:4])
    except (KeyError, ValueError):
        return True
    return abs(year - entry_year) <= YEARS_APART


def sanitize_string(s):
    s = s.lower().strip()
    # Get rid of chars in EXCLUDE_CHARS
    s = ''.join(character for character in s if character not in EXCLUDE_CHARS)
    # Get rid of multiple spaces
    s = ' '.join(s.split())
    return s


def levenshtein_distance_ratio(s, t):
    """
    Calculates levenshtein distance ratio between two strings.
    The more similar the strings, the closer the result will be to 1.
    The farther disjunct the string, the closer the result to 0

    https://www.datacamp.com/community/tutorials/fuzzy-string-python
    """
    # Initialize matrix of zeros
    rows = len(s) + 1
    cols = len(t) + 1
    distance = [[0 for x in range(cols)] for y in range(rows)] 

    # Populate matrix of zeros with the indeces of each character of both strings
    for i in range(1, rows):
        for k in range(1,cols):
            distance[i][0] = i
            distance[0][k] = k

    # Iterate over the matrix to compute the cost of deletions,insertions and/or substitutions    
    for col in range(1, cols):
        for row in range(1, rows):
            if s[row-1] == t[col-1]:
                cost = 0 # If the characters are the same in the two strings in a given position [i,j] then the cost is 0
            else:
                # In order to align the results with those of the Python Levenshtein package, if we choose to calculate the ratio
                # the cost of a substitution is 2. If we calculate just distance, then the cost of a substitution is 1.
                cost = 2
            distance[row][col] = min(distance[row-1][col] + 1,      # Cost of deletions
                                 distance[row][col-1] + 1,          # Cost of insertions
                                 distance[row-1][col-1] + cost)     # Cost of substitutions
    return ((len(s)+len(t)) - distance[row][col]) / (len(s)+len(t))
