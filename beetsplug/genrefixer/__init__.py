#  Copyright: Copyright (c) 2020., <AUTHOR>
#  Author: <AUTHOR> <EMAIL>
#  License: See LICENSE.txt

import os

from beets.plugins import BeetsPlugin
from confuse import ConfigSource, load_yaml

from beetsplug.genrefixer.command import GenreFixerCommand


class TemplatePlugin(BeetsPlugin):
    _default_plugin_config_file_name_ = 'config_default.yml'

    def __init__(self):
        super(TemplatePlugin, self).__init__()
        config_file_path = os.path.join(os.path.dirname(__file__),
                                        self._default_plugin_config_file_name_)
        source = ConfigSource(load_yaml(config_file_path) or {},
                              config_file_path)
        self.config.add(source)

    def commands(self):
        return [GenreFixerCommand(self.config)]
