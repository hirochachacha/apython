#!/usr/bin/env python
#coding: utf-8

from __future__ import with_statement
import os
import sys
from itertools import chain
from six.moves import configparser


__all__ = ['loadini', 'Struct', 'default_config_path']

DEFAULT_COLORS = {
    'keyword': 'y',
    'name': 'c',
    'comment': 'b',
    'string': 'm',
    'error': 'r',
    'number': 'G',
    'operator': 'Y',
    'punctuation': 'y',
    'token': 'C',
    'background': 'd',
    'output': 'w',
    'main': 'c',
    'paren': 'R',
    'prompt': 'c',
    'prompt_more': 'g',
}


class Struct(object):
    """Simple class for instantiating objects we can add arbitrary attributes
    to and use for various arbitrary things."""


def get_config_home():
    """Returns the base directory for bpython's configuration files."""
    xdg_config_home = os.environ.get('XDG_CONFIG_HOME', '~/.config')
    return os.path.join(xdg_config_home, 'bpython')


def default_config_path():
    """Returns bpython's default configuration file path."""
    return os.path.join(get_config_home(), 'config')


def _loadini(struct, configfile):
    config_path = os.path.expanduser(configfile)
    if not os.path.isfile(config_path) and configfile == default_config_path():
        # We decided that '~/.bpython/config' still was a crappy
        # place, use XDG Base Directory Specification instead.  Fall
        # back to old config, though.
        config_path = os.path.expanduser('~/.bpython/config')

    config = configparser.ConfigParser()

    config.read(os.path.join(os.path.dirname(os.path.dirname(__file__)), "default", "config"))

    if not config.read(config_path):
        # No config file. If the user has it in the old place then complain
        if os.path.isfile(os.path.expanduser('~/.bpython.ini')):
            sys.stderr.write("Error: It seems that you have a config file at "
                             "~/.bpython.ini. Please move your config file to "
                             "%s\n" % default_config_path())
            sys.exit(1)

    struct.dedent_after = config.getint('general', 'dedent_after')
    struct.tab_length = config.getint('general', 'tab_length')
    struct.auto_display_list = config.getboolean('general',
                                                 'auto_display_list')
    struct.syntax = config.getboolean('general', 'syntax')
    struct.arg_spec = config.getboolean('general', 'arg_spec')
    struct.paste_time = config.getfloat('general', 'paste_time')
    struct.highlight_show_source = config.getboolean('general',
                                                     'highlight_show_source')
    struct.hist_file = config.get('general', 'hist_file')
    struct.hist_length = config.getint('general', 'hist_length')
    struct.hist_duplicates = config.getboolean('general', 'hist_duplicates')
    struct.flush_output = config.getboolean('general', 'flush_output')

    struct.cli_suggestion_width = config.getfloat('cli', 'suggestion_width')
    if struct.cli_suggestion_width <= 0 or struct.cli_suggestion_width > 1:
        struct.cli_suggestion_width = 0.8

    struct.cli_trim_prompts = config.getboolean('cli',
                                                'trim_prompts')
    struct.complete_magic_methods = config.getboolean('general',
                                                      'complete_magic_methods')
    methods = config.get('general', 'magic_methods')
    struct.magic_methods = [meth.strip() for meth in methods.split(",")]
    struct.autocomplete_mode = config.get('general', 'autocomplete_mode')
    struct.save_append_py = config.getboolean('general', 'save_append_py')
    struct.editor = config.get('general', 'editor')
    struct.word_delimiter = config.get('general', 'word_delimiter')
    struct.is_space_only_skip_char = config.get('general', 'is_space_only_skip_char')
    struct.statusbar_text = config.get('general', 'statusbar_text')
    color_scheme_name = config.get('general', 'color_scheme')

    if color_scheme_name == 'default':
        struct.color_scheme = DEFAULT_COLORS
    else:
        _populate_color_scheme(struct, color_scheme_name)


def _populate_color_scheme(struct, color_scheme_name):
    if color_scheme_name == 'default':
        struct.color_scheme = DEFAULT_COLORS
    else:
        struct.color_scheme = dict()

        theme_filename = color_scheme_name + '.theme'
        path = os.path.expanduser(os.path.join('~/.bpython', 'themes', theme_filename))
        default_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "default", "themes", theme_filename)

        for path in [path, default_path]:
            try:
                _load_theme(path, struct.color_scheme)
            except EnvironmentError:
                continue
            else:
                break
        else:
            sys.stderr.write("Could not load theme '%s'.\n" %
                             (color_scheme_name, ))
            sys.exit(1)


def _load_theme(path, colors):
    theme = configparser.ConfigParser()
    with open(path, 'r') as f:
        theme.readfp(f)
    for k, v in chain(theme.items('syntax'), theme.items('interface')):
        if theme.has_option('syntax', k):
            colors[k] = theme.get('syntax', k)
        else:
            colors[k] = theme.get('interface', k)

    # Check against default theme to see if all values are defined
    for k, v in DEFAULT_COLORS.items():
        if k not in colors:
            colors[k] = v
    f.close()


def loadini(struct, configfile):
    """Loads .ini configuration file and stores its values in struct"""

    _loadini(struct, configfile)
