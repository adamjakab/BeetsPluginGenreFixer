#  Copyright: Copyright (c) 2020., <AUTHOR>
#  Author: <AUTHOR> <EMAIL>
#  License: See LICENSE.txt

import logging
import os

from confuse import Subview
from beetsplug.genrefixer import dataprovider

# Get values as: plg_ns['__PLUGIN_NAME__']
plg_ns = {}
about_path = os.path.join(os.path.dirname(__file__), u'about.py')
with open(about_path) as about_file:
    exec(about_file.read(), plg_ns)

__logger__ = logging.getLogger('beets.{plg}'.format(
    plg=plg_ns['__PLUGIN_NAME__']))


def say(msg, log_only=True, is_error=False):
    _level = logging.DEBUG
    _level = _level if log_only else logging.INFO
    _level = _level if not is_error else logging.ERROR
    __logger__.log(level=_level, msg=msg)


def get_formatted_tag(tag):
    """Format a tag to correct case."""
    words = tag.split(' ')
    for i, word in enumerate(words):
        if len(word) < 3:
            words[i] = word.upper()
        else:
            words[i] = word.title()
    return ' '.join(words)


def get_normalized_tags(dp_response, _min=0.1):
    tags = {}
    if dp_response and len(dp_response) == 1 and 'tags' in dp_response[0]:
        t = dp_response[0]["tags"]
        if len(t):
            _max = max(t.values())
            if _max == 0:
                score = 1
                t = {it[0]: score / (i + 1) for i, it in
                     enumerate(t.items())}
                _max = max(t.values())

            tags = {k: round(v / _max, 3) for k, v in t.items()
                    if v / _max >= _min}

    return tags


def setup_dataproviders(provider_config: Subview):
    providers = []
    for pk in provider_config:
        try:
            pconf = provider_config[pk]
            if pconf["enabled"].get(bool):
                say("Enabling DP({}): {}".format(pk, pconf))
                providers.append(dataprovider.factory(pk, pconf))
        except dataprovider.DataProviderError as err:
            say('Data provider error: {}'.format(err))

    if not providers:
        raise RuntimeError(
            'No data providers are activated!')

    return providers
