#  Copyright: Copyright (c) 2020., <AUTHOR>
#  Author: <AUTHOR> <EMAIL>
#  License: See LICENSE.txt
import operator
from optparse import OptionParser

from beets.library import Library
from beets.ui import Subcommand, decargs
from beets.dbcore.query import MatchQuery, AndQuery, OrQuery, \
    NoneQuery, RegexpQuery
from beets.library import Library, Item, parse_query_parts
from beets.util.confit import Subview

from beetsplug.genrefixer import common


class GenreFixerCommand(Subcommand):
    config: Subview = None
    lib: Library = None
    query = None
    parser: OptionParser = None

    dataproviders = None

    cfg_force = False

    def __init__(self, cfg):
        self.config = cfg

        self.parser = OptionParser(
            usage='beet {plg} [options] [QUERY...]'.format(
                plg=common.plg_ns['__PLUGIN_NAME__']
            ))

        self.parser.add_option(
            '-f', '--force',
            action='store_true', dest='force', default=self.cfg_force,
            help=u'[default: {}] force analysis of items with non-zero bpm '
                 u'values'.format(
                self.cfg_force)
        )

        self.parser.add_option(
            '-v', '--version',
            action='store_true', dest='version', default=False,
            help=u'show plugin version'
        )

        super(GenreFixerCommand, self).__init__(
            parser=self.parser,
            name=common.plg_ns['__PLUGIN_NAME__'],
            aliases=[common.plg_ns['__PLUGIN_ALIAS__']] if
            common.plg_ns['__PLUGIN_ALIAS__'] else [],
            help=common.plg_ns['__PLUGIN_SHORT_DESCRIPTION__']
        )

    def func(self, lib: Library, options, arguments):
        self.lib = lib
        self.query = decargs(arguments)

        self.cfg_force = options.force

        if options.version:
            self.show_version_information()
            return

        self.handle_main_task()

    def handle_main_task(self):
        items = self.retrieve_library_items()
        if not items:
            self._say("Your query did not produce any results.", log_only=False)
            return

        self.dataproviders = common.setup_dataproviders(
            self.config["providers"])

        # for item in items:
        if True:
            item = items[0]
            self.process_item(item)
            # item.try_write()
            # item.store()

    def process_item(self, item: Item):
        self._say("Fixing item: {}".format(item), log_only=True)

        # Musicbrainz
        dp = self.dataproviders[0]
        self._say("{}: Musicbrainz".format("=" * 60))
        resp = dp.query_artist(item.get("artist"))
        tags = common.get_normalized_tags(resp)
        tags = {common.get_formatted_tag(k): v for k, v in tags.items()}
        tags = sorted(tags.items(), key=operator.itemgetter(1), reverse=True)

        self._say("Artist tags: {}".format(tags), log_only=False)

        resp = dp.query_album(item.get("mb_releasegroupid"),
                              artist=item.get("artist"), year=item.get("year"))
        tags = common.get_normalized_tags(resp)
        tags = {common.get_formatted_tag(k): v for k, v in tags.items()}
        tags = sorted(tags.items(), key=operator.itemgetter(1), reverse=True)
        self._say("Album tags: {}".format(tags), log_only=False)

        # LastFM
        # dp = self.dataproviders[1]
        # self._say("{}: LastFM".format("="*60))
        # tags = common.get_normalized_tags(dp.query_artist(item.get("artist")))
        # self._say("Artist tags: {}".format(tags), log_only=False)
        #
        # tags = common.get_normalized_tags(dp.query_album(item.get("album"),
        #                                             artist=item.get(
        #                                             "artist")))
        # self._say("Album tags: {}".format(tags), log_only=False)

    def retrieve_library_items(self):
        cmd_query = self.query
        parsed_cmd_query, parsed_ordering = parse_query_parts(cmd_query, Item)

        if self.cfg_force:
            full_query = parsed_cmd_query
        else:
            parsed_plg_query = OrQuery([
                RegexpQuery('genre', '^$'),
                RegexpQuery('genre', '[/,]'),
            ])
            full_query = AndQuery([parsed_cmd_query, parsed_plg_query])

        self._say("Selection query: {}".format(full_query))

        return self.lib.items(full_query, parsed_ordering)

    def show_version_information(self):
        self._say("{pt}({pn}) plugin for Beets: v{ver}".format(
            pt=common.plg_ns['__PACKAGE_TITLE__'],
            pn=common.plg_ns['__PACKAGE_NAME__'],
            ver=common.plg_ns['__version__']
        ), log_only=False)

    @staticmethod
    def _say(msg, log_only=True, is_error=False):
        common.say(msg, log_only, is_error)
