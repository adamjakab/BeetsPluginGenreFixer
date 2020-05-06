# whatlastgenre
# Improves genre metadata of audio files
# based on tags from various music sites.
#
# Copyright (c) 2012-2020 YetAnotherNerd
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.

"""whatlastgenre dataprovider

Contains classes for querying APIs of some music related sites.
"""

from __future__ import division, print_function, unicode_literals

import logging
import os.path
import time
from collections import defaultdict
from configparser import NoSectionError, NoOptionError
from datetime import timedelta

import requests

from beetsplug.genrefixer.about import __PACKAGE_TITLE__, __version__

try:  # use optional requests_cache if available
    import requests_cache

    requests_cache.install_cache(
        os.path.expanduser('~/.whatlastgenre/reqcache'),
        expire_after=timedelta(days=180),
        allowable_codes=(200, 404),
        allowable_methods=('GET', 'POST'),
        ignored_parameters=['oauth_timestamp',
                            'oauth_nonce',
                            'oauth_signature'])
except ImportError:
    requests_cache = None

HEADERS = {'User-Agent': '{}/{}'.format(__PACKAGE_TITLE__, __version__)}

LASTFM_API_KEY = ''

DISCOGS_KEY = ''
DISCOGS_SECRET = ''


def factory(name, conf):
    """Factory for DataProviders."""
    if name == 'discogs':
        dapr = Discogs(conf)
    elif name == 'lastfm':
        dapr = LastFM()
    elif name == 'mbrainz':
        dapr = MusicBrainz()
    else:
        raise DataProviderError('unknown dataprovider: %s' % name)
    return dapr


def get_stats(daprs):
    """Print some DataProvider statistics."""
    result = ['\n', 'Source stats  ',
              ''.join('| %-8s ' % d.name for d in daprs),
              '\n', '-' * 14, ('+' + '-' * 10) * len(daprs),
              '\n']
    for key in ['reqs_err', 'reqs_web', 'reqs_cache', 'reqs_lowcache',
                'results', 'results_none', 'results_many', 'results/req',
                'tags', 'tags/result', 'goodtags', 'goodtags/tag',
                'time_resp_avg', 'time_wait_avg']:
        stats = [d.get_stats(key) for d in daprs]
        if all(stats):
            result.append('%-13s ' % key)
            for val in stats:
                pat = '| %8d ' if val.is_integer() else '| %8.2f '
                result.append(pat % val)
            result.append('\n')
    return ''.join(result)


class DataProviderError(Exception):
    """If something went wrong with DataProviders."""
    pass


class DataProvider(object):
    """Base class for DataProviders."""

    def __init__(self):
        self.log = logging.getLogger(__name__)
        self.name = self.__class__.__name__
        self.rate_limit = 1.0  # min. seconds between requests
        self.last_request = 0
        self.stats = defaultdict(float)
        self.session = requests.Session()
        self._setup_session()

    def _setup_session(self):
        """Set session headers and mount HTTPAdapters with retries."""
        self.session.headers.update(HEADERS)
        adapter = requests.adapters.HTTPAdapter(max_retries=3)
        for prefix in ('http://', 'https://'):
            self.session.mount(prefix, adapter)

    def _wait_rate_limit(self):
        """Wait for the rate limit."""
        while time.time() - self.last_request < self.rate_limit:
            self.stats['time_wait'] += .1
            time.sleep(.1)

    def _request(self, url, params, method='GET'):
        """Send a request.

        Honor rate limits and record some timings for stats.

        :param url: url string
        :param params: dict of call parameters
        :param method: request method
        """
        self._wait_rate_limit()
        time_ = time.time()
        try:
            if method == 'POST':
                res = self.session.post(url, data=params)
            else:
                res = self.session.get(url, params=params)
        except requests.exceptions.TooManyRedirects as err:
            raise err
        except requests.exceptions.RequestException as err:
            self.log.debug(err)
            raise DataProviderError("request: %s" % err.message)
        if not getattr(res, 'from_cache', False):
            self.stats['reqs_web'] += 1
            self.stats['time_resp'] += time.time() - time_
            self.last_request = time_
        else:
            self.stats['reqs_lowcache'] += 1
        if res.status_code not in [200, 404]:
            raise DataProviderError(
                'status code %d: %s' % (res.status_code, res.reason))
        return res

    def _request_json(self, url, params, method='GET'):
        """Return a json response from a request."""
        res = self._request(url, params, method=method)
        try:
            return res.json()
        except ValueError as err:
            self.log.debug(res.text)
            raise DataProviderError("json request: %s" % err.message)

    def _prefilter_results(self, results, name, value, func):
        """Try to prefilter results."""
        res = [r for r in results if func(r) == value]
        if res and len(res) < len(results):
            self.log.info('prefilter %d of %d results by %s',
                          len(results) - len(res), len(results), name)
            results = res
        return results

    def get_stats(self, key):
        """Return stats by key."""
        value = None
        if key in self.stats:
            value = self.stats[key]
        elif key == 'reqs_total':
            value = sum([self.stats['reqs_web'],
                         self.stats['reqs_cache'],
                         self.stats['reqs_lowcache']])
        elif key == 'results/req' and self.get_stats('reqs_total'):
            value = self.stats['results'] / self.get_stats('reqs_total')
        elif key.startswith('time_') and self.stats['reqs_web']:
            value = self.stats[key[:-3]] / self.stats['reqs_web']
        elif key == 'tags/result' and self.stats['results']:
            value = self.stats['tags'] / self.stats['results']
        elif key == 'goodtags/tag' and self.stats['tags']:
            value = self.stats['goodtags'] / self.stats['tags']
        return value

    def query_artist(self, artist):
        """Query for artist data."""
        raise NotImplementedError()

    def query_album(self, album, artist=None, year=None, reltyp=None):
        """Query for album data."""
        raise NotImplementedError()

    def query_by_mbid(self, entity, mbid):
        """Query by mbid."""
        raise NotImplementedError()


class Discogs(DataProvider):
    """Discogs DataProvider"""

    def __init__(self, conf):
        super(Discogs, self).__init__()
        import rauth
        # http://www.discogs.com/developers/#header:home-rate-limiting
        self.rate_limit = 3.0
        self.conf = conf
        self.discogs = rauth.OAuth1Service(
            consumer_key=DISCOGS_KEY,
            consumer_secret=DISCOGS_SECRET,
            request_token_url='https://api.discogs.com/oauth/request_token',
            access_token_url='https://api.discogs.com/oauth/access_token',
            authorize_url='https://www.discogs.com/oauth/authorize')
        token = self._get_token_from_config()
        if not token or not all(token):
            token = self._get_token_from_user()
            self._save_token_to_config(token)
        self.session = self.discogs.get_session(token)
        self._setup_session()
        # avoid filling cache with unusable entries
        if requests_cache \
                and not hasattr(self.session.cache, '_ignored_parameters'):
            self.session._is_cache_disabled = True  # pylint: disable=W0212

    def _get_token_from_user(self):
        """Get token from user without requests_cache."""

        def get_token_from_user():
            """Get token from user."""
            req_token, req_secret = self.discogs.get_request_token(
                headers=HEADERS)
            print('Discogs requires authentication with your own account.\n'
                  'Disable discogs in the config file or use this link to '
                  'authenticate:\n%s'
                  % self.discogs.get_authorize_url(req_token))
            oauth_verifier = input('Verification code: ')
            try:
                token = self.discogs.get_access_token(
                    req_token, req_secret,
                    data={'oauth_verifier': oauth_verifier},
                    headers=HEADERS)
            except KeyError as err:
                raise RuntimeError(err.message)
            return token

        if requests_cache:
            with self.discogs.get_session().cache_disabled():
                return get_token_from_user()
        else:
            return get_token_from_user()

    def _get_token_from_config(self):
        """Get token from config file."""
        token = None
        try:
            token = (self.conf.get('discogs', 'token'),
                     self.conf.get('discogs', 'secret'))
        except (NoSectionError, NoOptionError):
            pass
        return token

    def _save_token_to_config(self, token):
        """Save token to config file."""
        if not self.conf.has_section('discogs'):
            self.conf.add_section('discogs')
        self.conf.set('discogs', 'token', token[0])
        self.conf.set('discogs', 'secret', token[1])
        self.conf.save()

    def query_artist(self, artist):
        """Query for artist data."""
        raise NotImplementedError()

    def query_album(self, album, artist=None, year=None, reltyp=None):
        """Query for album data."""
        params = {'release_title': album}
        if artist:
            params.update({'artist': artist})
        result = self._request_json('https://api.discogs.com/database/search',
                                    params)
        if not result['results']:
            return None
        # merge all releases and masters
        tags = set()
        for res in result['results']:
            if res['type'] in ['master', 'release']:
                for key in ['genre', 'style']:
                    tags.update(res.get(key))
        return [{'tags': {tag: 0 for tag in tags}}]

    def query_by_mbid(self, entity, mbid):
        """Query by mbid."""
        raise NotImplementedError()


class LastFM(DataProvider):
    """Last.FM DataProvider"""

    def __init__(self):
        super(LastFM, self).__init__()
        # http://lastfm.de/api/tos
        self.rate_limit = .25

    def _query(self, params):
        """Query Last.FM API."""
        params.update({'format': 'json',
                       'api_key': LASTFM_API_KEY
                       })
        result = self._request_json('http://ws.audioscrobbler.com/2.0/',
                                    params)
        if 'error' in result:
            self.log.debug('%-8s error: %s', self.name, result['message'])
            return None
        tags = result['toptags'].get('tag')
        if tags:
            if not isinstance(tags, list):
                tags = [tags]
            tags = {t['name']: int(t.get('count', 0)) for t in tags}
        return [{'tags': tags}]

    def query_artist(self, artist):
        """Query for artist data."""
        return self._query({'method': 'artist.gettoptags', 'artist': artist})

    def query_album(self, album, artist=None, year=None, reltyp=None):
        """Query for album data."""
        return self._query({'method': 'album.gettoptags', 'album': album,
                            'artist': artist or 'Various Artists'
                            })

    def query_by_mbid(self, entity, mbid):
        """Query by mbid."""
        if entity == 'album':
            # FIXME: seems broken at the moment,
            # http error 400: artist param missing,
            # resolve later when lastfm finished migration
            raise NotImplementedError()
        self.log.debug("%-8s %-6s use mbid '%s'.", self.name, entity, mbid)
        return self._query({'method': entity + '.gettoptags', 'mbid': mbid})


class MusicBrainz(DataProvider):
    """MusicBrainz DataProvider"""

    def __init__(self):
        super(MusicBrainz, self).__init__()
        # http://musicbrainz.org/doc/XML_Web_Service/Rate_Limiting
        self.rate_limit = 2.0
        self.name = 'MBrainz'

    def _query(self, path, params):
        """Query MusicBrainz."""
        params.update({'fmt': 'json', 'limit': 1})
        result = self._request_json(
            'http://musicbrainz.org/ws/2/' + path, params)
        if 'error' in result:
            self.log.debug('%-8s error: %s', self.name, result['error'])
            return None
        if 'query' in params:
            result = result[path + 's']
        else:  # by mbid
            result = [result]
        return [{'tags': {t['name']: int(t.get('count', 0))
                          for t in r.get('tags', {})}
                 } for r in result]

    def query_artist(self, artist):
        """Query for artist data."""
        return self._query('artist', {'query': 'artist: ' + artist})

    def query_album(self, album, artist=None, year=None, reltyp=None):
        """Query for album data."""
        return self._query('release-group' + '/' + album, {'inc': 'tags'})

    def query_by_mbid(self, entity, mbid):
        """Query by mbid."""
        self.log.debug("%-8s %-6s use mbid '%s'.", self.name, entity, mbid)
        if entity == 'album':
            entity = 'release-group'
        return self._query(entity + '/' + mbid, {'inc': 'tags'})
