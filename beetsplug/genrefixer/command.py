#  Copyright: Copyright (c) 2020., <AUTHOR>
#  Author: <AUTHOR> <EMAIL>
#  License: See LICENSE.txt
import operator
from optparse import OptionParser

from beets.library import Library
from beets.ui import Subcommand, decargs
from beets.dbcore.query import MatchQuery, AndQuery, OrQuery, \
    NoneQuery, RegexpQuery, FixedFieldSort
from beets.library import Library, Item, parse_query_parts
from confuse import Subview

from beetsplug.genrefixer import common


class GenreFixerCommand(Subcommand):
    config: Subview = None
    lib: Library = None
    query = None
    parser: OptionParser = None

    dataproviders = None

    _HATE_LIST_ = []
    _DISLIKE_LIST_ = []
    _LIKE_LIST_ = []
    _LOVE_LIST_ = []

    cfg_force = False

    def __init__(self, cfg):
        self.config = cfg

        self._HATE_LIST_ = self.config["hate_list"].get()
        self._DISLIKE_LIST_ = self.config["dislike_list"].get()
        self._LIKE_LIST_ = self.config["like_list"].get()
        self._LOVE_LIST_ = self.config["love_list"].get()

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

        self.setup_command()
        self.handle_main_task()
        self.shutdown_command()

    def setup_command(self):
        self.dataproviders = common.setup_dataproviders(
            self.config["providers"])

    def shutdown_command(self):
        # Shutdown dataproviders - saves cache
        for dp in self.dataproviders:
            dp.store_pickle_jar()

    def handle_main_task(self):
        items = self.retrieve_library_items()
        if not items:
            self._say("Your query did not produce any results.", log_only=False)
            return

        last_album = None
        for item in items:
            if self.process_item(item):
                item.try_write()
                item.store()

                # store genre on album as well
                # current_album = item.get("mb_releasegroupid")
                # if current_album != last_album:
                #     album = item.get_album()
                #     album["genre"] = item["genre"]
                #     album.store()
                #     last_album = current_album

    def process_item(self, item: Item):
        self._say("Fixing item: {}".format(item), log_only=True)
        current_genre = item.get("genre")

        tag_groups = []

        qtypes = (self.config["types"].keys())
        metadata = {
            'artist': item.get("artist"),
            'artistid': item.get("mb_artistid:"),
            'album': item.get("album"),
            'albumid': item.get("mb_releasegroupid"),
            'year': item.get("year")
        }

        for dp in self.dataproviders:
            # self._say("{}: {}".format("=" * 60, dp.name))
            for qtype in qtypes:
                tags = self.get_tags_from_provider(dp, qtype, metadata)
                # self._say("tags[{}]: {}".format(qtype, tags), log_only=False)
                if tags:
                    tag_groups.append({
                        'provider': dp.name,
                        'qtype': qtype,
                        'tags': tags
                    })

        # self._say("Tags: {}".format(tag_groups), log_only=False)

        tags = self.create_unified_tag_list(tag_groups)
        # self._say("Unified Tags: {}".format(tags), log_only=False)

        tags = self.get_scored_tags(tags)
        # self._say("Scored Tags: {}".format(tags), log_only=False)

        tags = sorted(tags.items(), key=operator.itemgetter(1), reverse=True)
        self._say("Ordered Tags: {}".format(tags), log_only=False)

        _max = self.config["max_tags"].as_number()
        _glue = self.config["tag_glue"].as_str()
        top_tags = [v[0] for v in tags][:_max]
        # self._say("Top Tags: {}".format(top_tags), log_only=False)

        changed = False
        if top_tags:
            new_genre = _glue.join(top_tags)
            if new_genre != current_genre:
                self._say("Setting new genre: '{}' -> '{}'"
                          .format(current_genre, new_genre), log_only=False)
                item["genre"] = new_genre
                changed = True

        return changed

    def get_scored_tags(self, tags):

        for k, v in tags.items():
            m = 1
            if k in self._HATE_LIST_:
                m = 0
            elif k in self._DISLIKE_LIST_:
                m = 0.5
            elif k in self._LIKE_LIST_:
                m = 1.5
            elif k in self._LOVE_LIST_:
                m = 3

            n = round(v * m, 3)
            # self._say("'{}': '{}' --(x{})--> {}".format(k,v,m,n))
            tags[k] = n

        return tags

    def create_unified_tag_list(self, tag_groups):
        ulist = {}
        for tg in tag_groups:
            provider = tg["provider"].lower()
            pweight = self.config["providers"][provider]["weight"].as_number()
            qtype = tg["qtype"].lower()
            tweight = self.config["types"][qtype]["weight"].as_number()
            tags = tg["tags"]
            for k, v in tags.items():
                v = v * pweight * tweight
                # self._say("tag[{}]: {}".format(k, v), log_only=False)
                if k in ulist:
                    v = ulist[k] + v
                ulist[k] = round(v, 3)

        return ulist

    def get_tags_from_provider(self, dp, qtype="album", metadata=None):
        resp = []

        try:
            if qtype == "artist":
                resp = dp.query_artist(metadata)
            elif qtype == "album":
                resp = dp.query_album(metadata)
            else:
                self._say("Unknown query type: {}".format(qtype), is_error=True)
        except NotImplementedError:
            pass

        tags = common.get_normalized_tags(resp)
        tags = {common.get_formatted_tag(k): v for k, v in tags.items()}

        return tags

    def retrieve_library_items(self):
        cmd_query = self.query
        parsed_cmd_query, parsed_ordering = parse_query_parts(cmd_query, Item)
        parsed_ordering = FixedFieldSort("albumartist", ascending=True)

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
