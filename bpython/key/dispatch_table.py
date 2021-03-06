#!/usr/bin/env python
#coding: utf-8

import curses
import re
import platform
from bpython._py3compat import chr
from bpython.repl import getpreferredencoding
from six import b, binary_type, text_type
from six.moves import filter, map, xrange


__all__ = ["dispatch_table", "CannotFindHandler"]


BLANK = re.compile(b(' +'))


class CannotFindHandler(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return "cannot find handler: %s" % self.value


class DispatchTable(object):
    def __init__(self):
        # self.keynames = []
        self._keymap = {}
        self._alias_keymap = {}
        self._dispatch_table = {}
        self._repl_dispatch_table = {}
        self._statusbar_dispatch_table = {}
        self._populate()

    def set_handler_on(self, ambiguous_keyname, function=None):
        def inner(function):
            if isinstance(ambiguous_keyname, list):
                keynames = map(self._get_precise_keyname, filter(bool, ambiguous_keyname))
                for keyname in keynames:
                    self._dispatch_table[keyname] = function
            elif isinstance(ambiguous_keyname, binary_type):
                keynames = map(self._get_precise_keyname, filter(bool, BLANK.split(ambiguous_keyname)))
                for keyname in keynames:
                    self._dispatch_table[keyname] = function
            elif isinstance(ambiguous_keyname, text_type):
                keynames = map(self._get_precise_keyname, filter(bool, BLANK.split(b(ambiguous_keyname))))
                for keyname in keynames:
                    self._dispatch_table[keyname] = function
            else:
                raise(Exception("bad argument error"))
        if function is None:
            return inner
        else:
            inner(function)

    def set_handler_on_clirepl(self, ambiguous_keyname, function=None):
        def inner(function):
            if isinstance(ambiguous_keyname, list):
                keynames = map(self._get_precise_keyname, filter(bool, ambiguous_keyname))
                for keyname in keynames:
                    self._repl_dispatch_table[keyname] = function
            elif isinstance(ambiguous_keyname, binary_type):
                keynames = map(self._get_precise_keyname, filter(bool, BLANK.split(ambiguous_keyname)))
                for keyname in keynames:
                    self._repl_dispatch_table[keyname] = function
            elif isinstance(ambiguous_keyname, text_type):
                keynames = map(self._get_precise_keyname, filter(bool, BLANK.split(b(ambiguous_keyname))))
                for keyname in keynames:
                    self._repl_dispatch_table[keyname] = function
            else:
                raise(Exception("bad argument error"))
        if function is None:
            return inner
        else:
            inner(function)

    def set_handler_on_statusbar(self, ambiguous_keyname, function=None):
        def inner(function):
            if isinstance(ambiguous_keyname, list):
                keynames = map(self._get_precise_keyname, filter(bool, ambiguous_keyname))
                for keyname in keynames:
                    self._statusbar_dispatch_table[keyname] = function
            elif isinstance(ambiguous_keyname, binary_type):
                keynames = map(self._get_precise_keyname, filter(bool, BLANK.split(ambiguous_keyname)))
                for keyname in keynames:
                    self._statusbar_dispatch_table[keyname] = function
            elif isinstance(ambiguous_keyname, text_type):
                keynames = map(self._get_precise_keyname, filter(bool, BLANK.split(b(ambiguous_keyname))))
                for keyname in keynames:
                    self._statusbar_dispatch_table[keyname] = function
            else:
                raise(Exception("bad argument error"))
        if function is None:
            return inner
        else:
            inner(function)

    def get_handler_on_clirepl(self, ambiguous_keyname):
        keyname = self._get_precise_keyname(ambiguous_keyname)
        if keyname in self._repl_dispatch_table:
            return self._repl_dispatch_table[keyname]
        elif keyname in self._dispatch_table:
            return self._dispatch_table[keyname]
        else:
            raise(CannotFindHandler(ambiguous_keyname))

    def get_handler_on_statusbar(self, ambiguous_keyname):
        keyname = self._get_precise_keyname(ambiguous_keyname)
        if keyname in self._statusbar_dispatch_table:
            return self._statusbar_dispatch_table[keyname]
        elif keyname in self._dispatch_table:
            return self._dispatch_table[keyname]
        else:
            raise(CannotFindHandler(ambiguous_keyname))

    def smart_match(self, ambiguous_keyname, str_or_list):
        if isinstance(str_or_list, list):
            keyname = self._get_precise_keyname(ambiguous_keyname)
            matches = map(self._get_precise_keyname, str_or_list)
            return keyname in matches
        else:
            keyname = self._get_precise_keyname(ambiguous_keyname)
            matches = self._get_precise_keyname(str_or_list)
            return keyname == matches

    def _get_precise_keyname(self, ambiguous_keyname):
        if isinstance(ambiguous_keyname, text_type):
            ambiguous_keyname = ambiguous_keyname.encode(getpreferredencoding())
        if ambiguous_keyname in self._keymap:
            return ambiguous_keyname
        elif ambiguous_keyname in self._alias_keymap:
            keyname = self._alias_keymap[ambiguous_keyname]
            return self._get_precise_keyname(keyname)
        else:
            #TODO need some warning for debugging
            return ambiguous_keyname

    def _populate(self):
        #if curses already initialized, do nothing.
        try:
            curses.keyname(1)
        except curses.error:
            curses.initscr()

        for i in xrange(curses.KEY_MAX):
            if i < (curses.KEY_MIN - 1):
                keyname = chr(i)
                self._keymap[keyname] = i

                long_keyname = curses.keyname(i)
                self._alias_keymap[long_keyname] = keyname

                if long_keyname.startswith(b("M-")):
                    self._alias_keymap[long_keyname.replace(b("M-"), b("m-"), 1)] = keyname
                    if long_keyname.startswith(b("M-^")):
                        self._alias_keymap[long_keyname.replace(b("M-^"), b("M-C-"), 1)] = keyname
                        self._alias_keymap[long_keyname.replace(b("M-^"), b("m-c-"), 1)] = keyname
                        self._alias_keymap[long_keyname.replace(b("M-^"), b("m-c-"), 1).lower()] = keyname
                elif long_keyname.startswith(b("^")):
                    self._alias_keymap[long_keyname.replace(b("^"), b("C-"), 1)] = keyname
                    self._alias_keymap[long_keyname.lower().replace(b("^"), b("C-"), 1)] = keyname
                    self._alias_keymap[long_keyname.replace(b("^"), b("c-"), 1)] = keyname
                    self._alias_keymap[long_keyname.lower().replace(b("^"), b("c-"), 1)] = keyname

            else:
                keyname = curses.keyname(i)
                if keyname:
                    self._keymap[keyname] = i

            # self.keynames.append(keyname)

        for k in self._keymap:
            if k.startswith(b("KEY_F(")):
                self._alias_keymap[k.lower()] = k
                self._alias_keymap[k.replace(b("KEY_F("), b("F"), 1)[:-1]] = k
                self._alias_keymap[k.replace(b("KEY_F("), b("f"), 1)[:-1]] = k
            elif k.startswith(b("KEY_")):
                self._alias_keymap[k.lower()] = k
                self._alias_keymap[k.replace(b("KEY_"), b(""), 1)] = k
                self._alias_keymap[k.replace(b("KEY_"), b(""), 1).lower()] = k

        for i in xrange(12):
            self._alias_keymap[b('S-F%s' % (i + 1))] = b('KEY_F(%s)' % (i + 13))
            self._alias_keymap[b('s-f%s' % (i + 1))] = b('KEY_F(%s)' % (i + 13))

        if platform.system() == 'Windows':
            self._alias_keymap[b('C_BACK')] = chr(127)
            self._alias_keymap[b('M-C_BACK')] = self._alias_keymap[b('M-') + curses.keyname(127)]
            self._alias_keymap[b('M-C_BACK')] = self._alias_keymap[b('m-') + curses.keyname(127)]
            self._alias_keymap[b('BACKSP')] = chr(8)
            self._alias_keymap[b('M-BACKSP')] = self._alias_keymap[b('M-') + curses.keyname(8)]
            self._alias_keymap[b('M-BACKSP')] = self._alias_keymap[b('m-') + curses.keyname(8)]
        else:
            self._alias_keymap[b('C_BACK')] = chr(8)
            self._alias_keymap[b('M-C_BACK')] = self._alias_keymap[b('M-') + curses.keyname(8)]
            self._alias_keymap[b('M-C_BACK')] = self._alias_keymap[b('m-') + curses.keyname(8)]
            self._alias_keymap[b('BACKSP')] = chr(127)
            self._alias_keymap[b('M-BACKSP')] = self._alias_keymap[b('M-') + curses.keyname(127)]
            self._alias_keymap[b('M-BACKSP')] = self._alias_keymap[b('m-') + curses.keyname(127)]

        self._alias_keymap[b('ESC')] = chr(27)
        self._alias_keymap[b('M-ESC')] = self._alias_keymap[b('M-') + curses.keyname(27)]
        self._alias_keymap[b('m-ESC')] = self._alias_keymap[b('M-') + curses.keyname(27)]


dispatch_table = DispatchTable()
