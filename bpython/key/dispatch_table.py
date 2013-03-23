#!/usr/bin/env python
#coding: utf-8

import curses
import re
import platform


__all__ = ["dispatch_table", "CannotFindHandler"]


BLANK = re.compile(r' +')


class CannotFindHandler(Exception):
    def __str__(self):
        return "cannot find handler: %s" % repr(self.value)


class DispatchTable(object):
    def __init__(self):
        # self.keynames = []
        self._keymap = {}
        self._alias_keymap = {}
        self._dispatch_table = {}
        self._populate()

    def set_handler_on(self, ambiguous_keyname, function=None):
        def inner(function):
            if isinstance(ambiguous_keyname, list):
                keynames = map(self._get_precise_keyname, filter(bool, ambiguous_keyname))
                for keyname in keynames:
                    self._dispatch_table[keyname] = function
            elif isinstance(ambiguous_keyname, str):
                keynames = map(self._get_precise_keyname, filter(bool, BLANK.split(ambiguous_keyname)))
                for keyname in keynames:
                    self._dispatch_table[keyname] = function
            else:
                raise(Exception("bad argument error"))
        if function == None:
            return inner
        else:
            inner(function)

    def get_handler_on(self, ambiguous_keyname):
        keyname = self._get_precise_keyname(ambiguous_keyname)
        if keyname in self._dispatch_table:
            return self._dispatch_table[keyname]
        else:
            raise(CannotFindHandler(ambiguous_keyname))

    def _get_precise_keyname(self, ambiguous_keyname):
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

        for i in range(curses.KEY_MAX):
            if i < (curses.KEY_MIN - 1):
                keyname = chr(i)
                self._keymap[keyname] = i

                long_keyname = curses.keyname(i)
                self._alias_keymap[long_keyname] = keyname

                if long_keyname.startswith("^"):
                    self._alias_keymap[long_keyname.replace("^", "C-", 1)] = keyname
                    self._alias_keymap[long_keyname.lower().replace("^", "C-", 1)] = keyname
                    self._alias_keymap[long_keyname.replace("^", "c-", 1)] = keyname
                    self._alias_keymap[long_keyname.lower().replace("^", "c-", 1)] = keyname
                elif long_keyname.startswith("M-"):
                    self._alias_keymap[long_keyname.replace("M-", "m-", 1)] = keyname

            else:
                keyname = curses.keyname(i)
                if keyname:
                    self._keymap[keyname] = i

            # self.keynames.append(keyname)

        for k in self._keymap:
            if k.startswith("KEY_F("):
                self._alias_keymap[k.lower()] = k
                self._alias_keymap[k.replace("KEY_F(", "F", 1)[:-1]] = k
                self._alias_keymap[k.replace("KEY_F(", "f", 1)[:-1]] = k
            elif k.startswith("KEY_"):
                self._alias_keymap[k.lower()] = k
                self._alias_keymap[k.replace("KEY_", "", 1)] = k
                self._alias_keymap[k.replace("KEY_", "", 1).lower()] = k

        for i in range(12):
            self._alias_keymap['S-F%s' % (i + 1)] = 'KEY_F(%s)' % (i + 13)
            self._alias_keymap['s-f%s' % (i + 1)] = 'KEY_F(%s)' % (i + 13)

        if platform.system() == 'Windows':
            self._alias_keymap['C_BACK'] = chr(127)
            self._alias_keymap['BACKSP'] = chr(8)
        else:
            self._alias_keymap['C_BACK'] = chr(8)
            self._alias_keymap['BACKSP'] = chr(127)

        self._alias_keymap['ESC'] = chr(27)


dispatch_table = DispatchTable()
