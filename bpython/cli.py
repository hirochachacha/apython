#!/usr/bin/env python
#coding: utf-8

# The MIT License
#
# Copyright (c) 2008 Bob Farrell
# Copyright (c) bpython authors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

# Modified by Brandon Navra
# Notes for Windows
# Prerequsites
#  - Curses
#  - pyreadline
#
# Added
#
# - Support for running on windows command prompt
# - input from numpad keys
#
# Issues
#
# - Suspend doesn't work nor does detection of resizing of screen
# - Instead the suspend key exits the program
# - View source doesn't work on windows unless you install the less program (From GnuUtils or Cygwin)

from __future__ import division, with_statement

import platform
import os
import sys
import curses
import math
import re
import time
import struct
import inspect

import bpython

if platform.system() != 'Windows':
    import signal      #Windows does not have job control
    import termios     #Windows uses curses
    import fcntl       #Windows uses curses
import unicodedata
import errno

from types import ModuleType

# These are used for syntax highlighting
from pygments import format
from bpython.formatter import BPythonFormatter

# This for completion
from bpython.completion.completers import import_completer
from bpython.completion import completer
from bpython.completion import inspection

# This for config
from bpython.config.struct import Struct

# This for i18n
from bpython import translations
from bpython.translations import _

from bpython import repl
from bpython.util import getpreferredencoding, debug, Dummy
import bpython.config.args

from bpython.interpreter import BPythonInterpreter, command_tokenize

from bpython._py3compat import PythonLexer, PY3, chr
from six.moves import map, xrange


# --- module globals ---
app = None
clipboard = []
# ---


class FakeStream(object):
    """Provide a fake file object which calls functions on the interface
    provided."""

    def __init__(self, interface):
        self.encoding = getpreferredencoding()
        self.interface = interface

    def flush(self):
        pass

    def write(self, s):
        self.interface.write(s)

    def writelines(self, l):
        for s in l:
            self.write(s)

    def isatty(self):
        # some third party (amongst them mercurial) depend on this
        return True


class FakeStdin(object):
    """Provide a fake stdin type for things like raw_input() etc."""

    def __init__(self, interface):
        """Take the curses Repl on init and assume it provides a get_key method
        which, fortunately, it does."""

        self.encoding = getpreferredencoding()
        self.interface = interface
        self.buffer = list()

    def __iter__(self):
        return iter(self.readlines())

    def flush(self):
        """Flush the internal buffer. This is a no-op. Flushing stdin
        doesn't make any sense anyway."""

    def write(self, value):
        # XXX IPython expects sys.stdin.write to exist, there will no doubt be
        # others, so here's a hack to keep them happy
        raise IOError(errno.EBADF, "sys.stdin is read-only")

    def isatty(self):
        return True

    def readline(self, size=-1):
        """I can't think of any reason why anything other than readline would
        be useful in the context of an interactive interpreter so this is the
        only one I've done anything with. The others are just there in case
        someone does something weird to stop it from blowing up."""

        if not size:
            return ''
        elif self.buffer:
            buffer = self.buffer.pop(0)
        else:
            buffer = ''

        curses.raw(True)
        try:
            while not buffer.endswith(('\n', '\r')):
                key = self.interface.get_key()
                if key in [curses.erasechar(), 'KEY_BACKSPACE']:
                    y, x = self.interface.scr.getyx()
                    if buffer:
                        self.interface.scr.delch(y, x - 1)
                        buffer = buffer[:-1]
                    continue
                elif key == chr(4) and not buffer:
                    # C-d
                    return ''
                elif (key not in ('\n', '\r') and
                          (len(key) > 1 or unicodedata.category(key) == 'Cc')):
                    continue
                sys.stdout.write(key)
                # Include the \n in the buffer - raw_input() seems to deal with trailing
                # linebreaks and will break if it gets an empty string.
                buffer += key
        finally:
            curses.raw(False)

        if size > 0:
            rest = buffer[size:]
            if rest:
                self.buffer.append(rest)
            buffer = buffer[:size]

        if PY3:
            return buffer
        else:
            return buffer.encode(getpreferredencoding())

    def read(self, size=None):
        if size == 0:
            return ''

        data = list()
        while size is None or size > 0:
            line = self.readline(size or -1)
            if not line:
                break
            if size is not None:
                size -= len(line)
            data.append(line)

        return ''.join(data)

    def readlines(self, size=-1):
        return list(iter(self.readline(size)))


class FakeDict(object):
    """Very simple dict-alike that returns a constant value for any key -
    used as a hacky solution to using a colours dict containing colour codes if
    colour initialisation fails."""

    def __init__(self, val):
        self._val = val

    def __getitem__(self, k):
        return self._val


class CLIInteraction(repl.Interaction):
    def __init__(self, config, statusbar=None):
        repl.Interaction.__init__(self, config, statusbar)

    def confirm(self, q):
        """Ask for yes or no and return boolean"""
        try:
            reply = self.statusbar.prompt(q)
        except ValueError:
            return False

        return reply.lower() in (_('y'), _('yes'))

    def notify(self, s, n=10):
        return self.statusbar.message(s, n)

    def file_prompt(self, s):
        return self.statusbar.prompt(s)


class ListBox(object):
    def __init__(self, scr, config, format_docstring=None):
        self.scr = scr
        self.config = config
        self.format_docstring = format_docstring

        self.topline = None
        self.nosep = False

        self.rows = 0
        self.cols = 0
        self.wl = 0
        self.docstring = None

        self.max_h = 0
        self.max_w = 0

        self.w = 0
        self.y = 0

        self.items = []
        self.index = -1
        self.v_items = []
        self.v_index = -1
        self.down = 0
        self.height_offset = 0

    def reset_with(self, repl_, nosep=False):
        y, _ = repl_.scr.getyx()
        h, w = repl_.scr.getmaxyx()
        down = (y < h // 2)
        if down:
            max_h = h - y
        else:
            max_h = y + 1
        max_w = int(w * self.config.cli_suggestion_width)

        self.nosep = nosep
        self.down = down
        self.max_h = max_h
        self.max_w = max_w
        self.y = y
        self.items = repl_.matches
        self.sync(repl_.matches_iter)
        self.topline = repl_.argspec
        if hasattr(repl_.argspec, 'docstring'):
            self.docstring = repl_.argspec.docstring
        else:
            self.docstring = None

    def show(self):
        if self.docstring is not None and len(self.items) < 2:
            self.height_offset = self._show_topline() + 1
            self._prepare_doc()
            self._show_doc()
        elif self.items:
            self.height_offset = self._show_topline() + 1
            self._prepare_v_items()
            self._show_v_items()
        else:
            app.clirepl.list_win_visible = False
            app.clirepl.redraw()

    def sync(self, matches_iter):
        self.index = matches_iter.index

    def next_page(self, matches_iter):
        if self.v_items[-1] == '...':
            if matches_iter.is_wait:
                self.v_index += 1
            matches_iter.index += (len(self.v_items) - self.v_index -1)
            self.sync(matches_iter)
            self._prepare_v_items()
            self.v_index -= 1
            self._show_v_items()
            matches_iter.wait()

    def refresh(self):
        self.scr.attron(app.get_colpair('main'))
        self.scr.border()
        self.scr.refresh()

    def addstr(self, s, *args):
        if not PY3 and isinstance(s, unicode):
            s = s.encode(getpreferredencoding(), errors='ignore')
        return self.scr.addstr(s, *args)

    def _show_topline(self):
        """This figures out what to do with the argspec and puts it nicely into
        the list window. It returns the number of lines used to display the
        argspec.  It's also kind of messy due to it having to call so many
        addstr() to get the colouring right, but it seems to be pretty
        sturdy."""

        self.scr.erase()
        r = 3
        if self.nosep:
            return 3

        if self.topline is None:
            self.scr.resize(3, self.max_w)
            self.addstr('\n  ')
            return r

        elif isinstance(self.topline, inspection.ArgSpec):
            fn = self.topline[0]
            args = self.topline[1][0]
            kwargs = self.topline[1][3]
            _args = self.topline[1][1]
            _kwargs = self.topline[1][2]
            is_bound_method = self.topline[2]
            in_arg = self.topline[3]
            if PY3:
                kwonly = self.topline[1][4]
                kwonly_defaults = self.topline[1][5] or dict()
            self.scr.resize(3, self.max_w)
            h, w = self.scr.getmaxyx()

            self.addstr('\n  ')
            self.addstr(fn,
                            app.get_colpair('name') | curses.A_BOLD)
            self.addstr(': (', app.get_colpair('name'))
            max_h = app.clirepl.scr.getmaxyx()[0]

            if is_bound_method and isinstance(in_arg, int):
                in_arg += 1

            punctuation_colpair = app.get_colpair('punctuation')

            for k, i in enumerate(args):
                _, x = self.scr.getyx()
                ln = len(str(i))
                kw = None
                if kwargs and k + 1 > len(args) - len(kwargs):
                    kw = repr(kwargs[k - (len(args) - len(kwargs))])
                    ln += len(kw) + 1

                if ln + x >= w:
                    ty = self.scr.getbegyx()[0]
                    if not self.down and ty > 0:
                        h += 1
                        self.scr.mvwin(ty - 1, 1)
                        self.scr.resize(h, w)
                    elif self.down and h + r < max_h - ty:
                        h += 1
                        self.scr.resize(h, w)
                    else:
                        break
                    r += 1
                    self.addstr('\n\t')

                if str(i) == 'self' and k == 0:
                    color = app.get_colpair('name')
                else:
                    color = app.get_colpair('token')

                if k == in_arg or i == in_arg:
                    color |= curses.A_BOLD

                if not PY3:
                    # See issue #138: We need to format tuple unpacking correctly
                    # We use the undocumented function inspection.strseq() for
                    # that. Fortunately, that madness is gone in Python 3.
                    self.addstr(inspect.strseq(i, str), color)
                else:
                    self.addstr(str(i), color)
                if kw is not None:
                    self.addstr('=', punctuation_colpair)
                    self.addstr(kw, app.get_colpair('token'))
                if k != len(args) - 1:
                    self.addstr(', ', punctuation_colpair)

            if _args:
                if args:
                    self.addstr(', ', punctuation_colpair)
                self.addstr('*%s' % (_args, ),
                                app.get_colpair('token'))

            if PY3 and kwonly:
                if not _args:
                    if args:
                        self.addstr(', ', punctuation_colpair)
                    self.addstr('*', punctuation_colpair)
                marker = object()
                for arg in kwonly:
                    self.addstr(', ', punctuation_colpair)
                    color = app.get_colpair('token')
                    if arg == in_arg:
                        color |= curses.A_BOLD
                    self.addstr(arg, color)
                    default = kwonly_defaults.get(arg, marker)
                    if default is not marker:
                        self.addstr('=', punctuation_colpair)
                        self.addstr(repr(default),
                                        app.get_colpair('token'))

            if _kwargs:
                if args or _args or (PY3 and kwonly):
                    self.addstr(', ', punctuation_colpair)
                self.addstr('**%s' % (_kwargs, ),
                                app.get_colpair('token'))
            self.addstr(')', punctuation_colpair)
            return r

        elif isinstance(self.topline, inspection.CommandSpec):
            name = self.topline[0]

            self.scr.resize(3, self.max_w)

            self.addstr('\n  ')
            self.addstr(name, app.get_colpair('name') | curses.A_BOLD)
            self.addstr(': ', app.get_colpair('name'))
            self.addstr('command', app.get_colpair('command'))
            return r

        elif isinstance(self.topline, inspection.KeySpec):
            name = self.topline[0]

            self.scr.resize(3, self.max_w)

            self.addstr('\n  ')
            self.addstr(name, app.get_colpair('name') | curses.A_BOLD)
            self.addstr(': ', app.get_colpair('name'))
            self.addstr('keyword', app.get_colpair('keyword'))
            self.docstring = ""
            return r

        elif isinstance(self.topline, inspection.ImpSpec):
            obj_name = self.topline[0]
            obj = self.topline[1]

            self.scr.resize(3, self.max_w)

            self.addstr('\n  ')

            if obj is None:
                class_name = 'module'
            elif inspect.isclass(obj):
                class_name = 'class'
            elif hasattr(obj, '__class__') and hasattr(obj.__class__, '__name__'):
                class_name = obj.__class__.__name__
            else:
                class_name = 'unknown'

            if not (self.docstring is not None and len(self.items) < 2) and class_name == "module":
                try:
                    for summary in self.docstring.split('\n'):
                        if summary.strip:
                            break
                except:
                    summary = ""
                self.addstr(summary, app.get_colpair('keyword'))
            else:

                self.addstr(obj_name, app.get_colpair('name') | curses.A_BOLD)
                self.addstr(': ', app.get_colpair('string'))
                self.addstr(class_name, app.get_colpair('keyword'))
            return r

        elif isinstance(self.topline, inspection.ObjSpec):
            obj_name = self.topline[0]
            obj = self.topline[1]

            self.scr.resize(3, self.max_w)

            self.addstr('\n  ')

            if inspect.isclass(obj):
                class_name = 'class'
            elif hasattr(obj, '__class__') and hasattr(obj.__class__, '__name__'):
                class_name = obj.__class__.__name__
            else:
                class_name = 'unknown'

            val = ""
            if isinstance(obj, (int, float, complex, list, dict, set, tuple)):
                val = str(obj)
            elif not PY3 and isinstance(obj, long):
                val = str(obj)
            elif isinstance(obj, str):
                val = '"' + obj + '"'
            elif not PY3 and isinstance(obj, unicode):
                val = 'u"' + obj + '"'
            elif isinstance(obj, Dummy):
                class_name = obj.class_name
            elif obj is None:
                return r

            self.addstr(obj_name, app.get_colpair('name') | curses.A_BOLD)
            if val:
                if len(val) > self.max_w - 8 - len(obj_name):
                    val = val[:self.max_w - 11 - len(obj_name)] + '...'
                self.addstr(' = ', app.get_colpair('string'))
                self.addstr(val, app.get_colpair('keyword'))
                self.docstring = ""
            else:
                self.addstr(': ', app.get_colpair('string'))
                self.addstr(class_name, app.get_colpair('keyword'))
            return r

        elif isinstance(self.topline, inspection.NoSpec):
            self.scr.resize(3, self.max_w)
            self.addstr('\n  ')
            return r


    def _show_doc(self):
        self.scr.resize(self.rows, self.w)

        if self.down:
            self.scr.mvwin(self.y + 1, 0)
        else:
            self.scr.mvwin(self.y - self.rows - 2, 0)

        if not PY3 and isinstance(self.docstring, unicode):
            self.docstring = self.docstring.encode(getpreferredencoding(), 'ignore')
        self.addstr('\n' + self.docstring, app.get_colpair('comment'))
        # XXX: After all the trouble I had with sizing the list box (I'm not very good
        # at that type of thing) I decided to do this bit of tidying up here just to
        # make sure there's no unnececessary blank lines, it makes things look nicer.

        h = self.scr.getyx()[0] + 2
        self.scr.resize(h, self.w)

    def _show_v_items(self):

        self.scr.resize(self.rows + 2, self.w)

        if self.down:
            self.scr.mvwin(self.y + 1, 0)
        else:
            self.scr.mvwin(self.y - self.rows - 2, 0)

        self.addstr('\n ')

        if not PY3:
            encoding = getpreferredencoding()
        for ix, i in enumerate(self.v_items):
            padding = (self.wl - len(i)) * ' '
            if ix == self.v_index:
                color = app.get_colpair('operator')
            else:
                color = app.get_colpair('main')
            if not PY3:
                i = i.encode(encoding)
            self.addstr(i + padding, color)
            if ((self.cols == 1 or (ix and not (ix + 1) % self.cols))
                and ix + 1 < len(self.v_items)):
                self.addstr('\n ')

        h = self.scr.getyx()[0] + 2
        self.scr.resize(h, self.w)

    def _prepare_doc(self):
        self.v_items = []
        self.rows = 1
        self.cols = 1
        self.wl = 2

        if self.rows + self.height_offset < self.max_h:
            self.rows += self.height_offset

        self.w = self.max_w

        docstrings = self.format_docstring(self.docstring, self.max_w - 2,
                                           self.max_h - self.height_offset)
        self.docstring = ''.join(docstrings)
        self.rows += len(docstrings)

    def _prepare_v_items(self):
        if not self.nosep:
            self._trim_items()

        self.v_items = []
        rows = 0
        cols = 0
        wl = 1

        v_index = self.index
        # visible items (we'll append until we can't fit any more in)
        for i, item in enumerate(self.items):
            item = item[:self.max_w - 3]
            self.v_items.append(item)
            wl = max(len(item), wl)
            cols = ((self.max_w - 2) // (wl + 1)) or 1
            rows = len(self.v_items) // cols

            if cols * rows < len(self.v_items):
                rows += 1

            if rows + self.height_offset - 1 >= self.max_h:
                rows = self.max_h - (self.height_offset - 1)
                if self.index < i - 1:
                    del self.v_items[-1]
                    self.v_items[-1] = '...'
                    self.v_index = v_index
                    break
                else:
                    v_index -= (len(self.v_items) - 3)
                    self.v_items = ['...', self.items[i - 1], self.items[i]]
                    continue
        else:
            rows += 1
            self.v_index = v_index % (len(self.v_items) + 1)

        self.rows = rows
        self.cols = cols
        self.wl = wl + 1

        if self.wl + 3 > self.max_w:
            self.w = self.max_w
        else:
            t = (self.cols + 1) * self.wl + 3
            if t > self.max_w:
                t = self.max_w
            self.w = t

    def _trim_items(self):
        if self.items:
            sep = '.'
            if os.path.sep in self.items[0]:
                # Filename completion
                sep = os.path.sep
            if sep in self.items[0]:
                self.items = [x.rstrip(sep).rsplit(sep)[-1] for x in self.items]

class Editable(object):
    def __init__(self, scr, config):
        from bpython.key.dispatcher import Dispatcher

        self.scr = scr
        self.config = config
        self.s = ''
        self.cut_buffer = clipboard
        self.word_delimiter = set(config.word_delimiter)
        self.cpos = 0
        self.do_exit = False
        self.last_key_press = time.time()
        self.paste_mode = False
        self.idle = App.idle
        self.highlighted_paren = None
        self.key_dispatcher = Dispatcher(self)
        self.iy, self.ix = self.scr.getyx()

    def _get_width(self, c):
        if unicodedata.east_asian_width(c) in 'WFA':
            return 2
        else:
            if ord(c) < 32:
                return 2
            else:
                return 1

    def p_key(self, key):
        return self.key_dispatcher.run(key)

    def get_key(self):
        key = ''
        while True:
            try:
                key += self.scr.getkey()
                if PY3:
                    # Seems like we get a in the locale's encoding
                    # encoded string in Python 3 as well, but of
                    # type str instead of bytes, hence convert it to
                    # bytes first and decode then
                    key = key.encode('latin-1').decode(getpreferredencoding())
                else:
                    key = key.decode(getpreferredencoding())
                self.scr.nodelay(False)
            except UnicodeDecodeError:
                # Yes, that actually kind of sucks, but I don't see another way to get
                # input right
                self.scr.nodelay(True)
            except curses.error:
                # I'm quite annoyed with the ambiguity of this exception handler. I previously
                # caught "curses.error, x" and accessed x.message and checked that it was "no
                # input", which seemed a crappy way of doing it. But then I ran it on a
                # different computer and the exception seems to have entirely different
                # attributes. So let's hope getkey() doesn't raise any other crazy curses
                # exceptions. :)
                self.scr.nodelay(False)
                # XXX What to do here? Raise an exception?
                if key:
                    return key
            else:
                if key != '\x00':
                    t = time.time()
                    self.paste_mode = (
                        t - self.last_key_press <= self.config.paste_time
                    )
                    self.last_key_press = t
                    return key
                else:
                    key = ''
            finally:
                if self.idle:
                    self.idle(self)

    def get_line(self):
        while True:
            key = self.get_key()
            if self.p_key(key) is None:
                return self.s

    def addstr(self, s):
        """Add a string to the current input line and figure out
        where it should go, depending on the cursor position."""
        if not self.cpos:
            self.s += s
        else:
            l = len(self.s)
            self.s = self.s[:l - self.cpos] + s + self.s[l - self.cpos:]

    def mvc(self, i, refresh=True):
        """This method moves the cursor relatively from the current
        position, where:
            0 == (right) end of current line
            length of current line len(self.s) == beginning of current line
        and:
            current cursor position + i
            for positive values of i the cursor will move towards the beginning
            of the line, negative values the opposite."""
        if i == 0:
            return False

        y, x = self.scr.getyx()

        if self.is_end_of_the_line and i < 0:
            return False

        if x == self.ix and y == self.iy and i >= 1:
            return False

        s_width = list(map(self._get_width, self.s))
        width = 0
        if i > 0:
            if i == 1:
                width = s_width[- self.cpos - 1]
            else:
                for _ in xrange(i):
                    self.mvc(1)
        elif i == 0:
            return False
        else:
            if i == -1:
                width = - s_width[- self.cpos]
            else:
                for _ in xrange(-i):
                    self.mvc(-1)

        h, w = App.gethw()

        if x - width < 0:
            y -= 1
            x = w

        if x - width >= w:
            y += 1
            x = 0 + i

        self.cpos += i
        self.scr.move(y, x - width)

        if refresh:
            self.scr.refresh()
        return True

    def check(self):
        """Check if paste mode should still be active and, if not, deactivate
        it and force syntax highlighting."""
        if (self.paste_mode
            and time.time() - self.last_key_press > self.config.paste_time):
            self.paste_mode = False
            self.print_line(self.s)

    @property
    def is_beginning_of_the_line(self):
        return self.cpos == len(self.s)

    @property
    def is_end_of_the_line(self):
        return self.cpos == 0

    @property
    def is_empty_line(self):
        return not self.s

    @property
    def is_start_of_the_line(self):
        """Return True or False accordingly if the cursor is at the beginning
        of the line (whitespace is ignored). This exists so that p_key() knows
        how to handle the tab key being pressed - if there is nothing but white
        space before the cursor then process it as a normal tab otherwise
        attempt tab completion."""
        return not self.s.lstrip()

    def clear_wrapped_lines(self):
        """Clear the wrapped lines of the current input."""
        # curses does not handle this on its own. Sad.
        height, width = self.scr.getmaxyx()
        max_y = min(self.iy + (self.ix + len(self.s)) // width + 1, height)
        for y in xrange(self.iy + 1, max_y):
            self.scr.move(y, 0)
            self.scr.clrtoeol()

    def echo(self, s, redraw=True):
        """Parse and echo a formatted string with appropriate attributes. It
        uses the formatting method as defined in formatter.py to parse the
        srings. It won't update the screen if it's reevaluating the code (as it
        does with undo)."""
        if not PY3 and isinstance(s, unicode):
            s = s.encode(getpreferredencoding())

        a = app.get_colpair('output')
        if '\x01' in s:
            rx = re.search('\x01([A-Za-z])([A-Za-z]?)', s)
            if rx:
                fg = rx.groups()[0]
                bg = rx.groups()[1]
                col_num = self._C[fg.lower()]
                if bg and bg != 'I':
                    col_num *= self._C[bg.lower()]

                a = curses.color_pair(int(col_num) + 1)
                if bg == 'I':
                    a |= curses.A_REVERSE
                s = re.sub('\x01[A-Za-z][A-Za-z]?', '', s)
                if fg.isupper():
                    a |= curses.A_BOLD
        s = s.replace('\x03', '')
        s = s.replace('\x01', '')

        # Replace NUL bytes, as addstr raises an exception otherwise
        s = s.replace('\0', '')
        # Replace \r\n bytes, as addstr remove the current line otherwise
        s = s.replace('\r\n', '\n')

        self.scr.addstr(s, a)

        if redraw:
            if hasattr(self, 'evaluating') and not getattr(self, 'evaluating'):
                pass
            else:
                self.scr.refresh()

    def print_line(self, s, clr=False, newline=False):
        """Chuck a line of text through the highlighter, move the cursor
        to the beginning of the line and output it to the screen."""

        if not s:
            clr = True

        if self.highlighted_paren is not None:
            # Clear previous highlighted paren
            self.reprint_line(*self.highlighted_paren)
            self.highlighted_paren = None

        if hasattr(self, 'paste_mode') and hasattr(self, 'tokenize') and hasattr(self, 'formatter'):
            if self.config.syntax and (not self.paste_mode or newline):
                o = format(self.tokenize(s, newline), self.formatter)
            else:
                o = s
        else:
            o = s

        self.f_string = o
        self.scr.move(self.iy, self.ix)

        if clr:
            self.scr.clrtoeol()

        if clr and not s:
            self.scr.refresh()

        if o:
            for t in o.split('\x04'):
                self.echo(t.rstrip('\n'))

        if self.cpos:
            t = self.cpos
            self.cpos = 0
            for _ in xrange(t):
                self.mvc(1)

    def reprint_line(self, lineno, tokens):
        """Helper function for paren highlighting: Reprint line at offset
        `lineno` in current input buffer."""
        if not self.buffer or lineno == len(self.buffer):
            return

        real_lineno = self.iy
        height, width = self.scr.getmaxyx()
        for i in xrange(lineno, len(self.buffer)):
            string = self.buffer[i]
            # 4 = length of prompt
            length = len(string.encode(getpreferredencoding())) + 4
            real_lineno -= int(math.ceil(length / width))
        if real_lineno < 0:
            return

        self.scr.move(real_lineno,
                      len(self.ps1) if lineno == 0 else len(self.ps2))
        line = format(tokens, BPythonFormatter(self.config.color_scheme))
        for string in line.split('\x04'):
            self.echo(string)

    def self_insert(self, key):
        self.addstr(key)
        self.print_line(self.s)

    def backward_character(self):
        self.mvc(1)

    def forward_character(self):
        self.mvc(-1)

    def backward_word(self):
        if self.is_empty_line:
            pass
        else:
            pos = len(self.s) - self.cpos - 1
            if self.config.is_space_only_skip_char:
                while pos >= 0 and self.s[pos] == ' ':
                    pos -= 1
                    self.backward_character()
                if pos >= 0 and self.s[pos] in self.word_delimiter:
                    pos -= 1
                    self.backward_character()
                while pos >= 0 and self.s[pos] == ' ':
                    pos -= 1
                    self.backward_character()
            else:
                while pos >= 0 and self.s[pos] in self.word_delimiter:
                    pos -= 1
                    self.backward_character()
            while pos >= 0 and self.s[pos] not in self.word_delimiter:
                pos -= 1
                self.backward_character()

    def forward_word(self):
        if self.is_empty_line:
            pass
        else:
            len_s = len(self.s)
            pos = len_s - self.cpos - 1
            if self.config.is_space_only_skip_char:
                while len_s > pos and self.s[pos] == ' ':
                    pos += 1
                    self.forward_character()
                if len_s > pos and self.s[pos] in self.word_delimiter:
                    pos += 1
                    self.forward_character()
                while len_s > pos and self.s[pos] == ' ':
                    pos += 1
                    self.forward_character()
            else:
                while len_s > pos and self.s[pos] in self.word_delimiter:
                    pos += 1
                    self.forward_character()
            while len_s > pos and self.s[pos] not in self.word_delimiter:
                pos += 1
                self.forward_character()

    def backward_delete_character(self, delete_tabs=True):
        """Process a backspace"""
        y, x = self.scr.getyx()
        if self.is_empty_line or self.is_beginning_of_the_line:
            return
        if x == self.ix and y == self.iy:
            return
        n = 1
        self.clear_wrapped_lines()
        if not self.cpos:
            # I know the nested if blocks look nasty. :(
            if self.is_start_of_the_line and delete_tabs:
                n = len(self.s) % self.config.tab_length
                if not n:
                    n = self.config.tab_length
            self.s = self.s[:-n]
        else:
            self.s = self.s[:-self.cpos - 1] + self.s[-self.cpos:]
        self.print_line(self.s, clr=True)
        return n

    def delete_character(self):
        """Process a del"""
        if self.is_empty_line:
            return

        if self.mvc(-1):
            self.backward_delete_character(False)

    def kill_word(self):
        if self.is_empty_line:
            pass
        else:
            deleted = []
            len_s = len(self.s)
            pos = len_s - self.cpos
            if self.config.is_space_only_skip_char:
                while self.cpos > 0 and self.s[pos] == ' ':
                    deleted.append(self.s[pos])
                    self.delete_character()
                    # Then we delete a full word.
                if self.cpos > 0 and self.s[pos] in self.word_delimiter:
                    deleted.append(self.s[pos])
                    self.delete_character()
                while self.cpos > 0 and self.s[pos] == ' ':
                    deleted.append(self.s[pos])
                    self.delete_character()
                    # Then we delete a full word.
            else:
                while self.cpos > 0 and self.s[pos] in self.word_delimiter:
                    deleted.append(self.s[pos])
                    self.delete_character()
            while self.cpos > 0 and self.s[pos] not in self.word_delimiter:
                deleted.append(self.s[pos])
                self.delete_character()
            self.cut_buffer.append(''.join(deleted))

    def backward_kill_word(self):
        if self.is_empty_line:
            pass
        else:
            pos = len(self.s) - self.cpos - 1
            deleted = []
            # First we delete any space to the left of the cursor.
            if self.config.is_space_only_skip_char:
                while pos >= 0 and self.s[pos] == ' ':
                    deleted.append(self.s[pos])
                    pos -= self.backward_delete_character()
                    # Then we delete a full word.
                if pos >= 0 and self.s[pos] in self.word_delimiter:
                    deleted.append(self.s[pos])
                    pos -= self.backward_delete_character()
                while pos >= 0 and self.s[pos] == ' ':
                    deleted.append(self.s[pos])
                    pos -= self.backward_delete_character()
                    # Then we delete a full word.
            else:
                while pos >= 0 and self.s[pos] in self.word_delimiter:
                    deleted.append(self.s[pos])
                    pos -= self.backward_delete_character()
            while pos >= 0 and self.s[pos] not in self.word_delimiter:
                deleted.append(self.s[pos])
                pos -= self.backward_delete_character()
            self.cut_buffer.append(''.join(reversed(deleted)))

    def kill_line(self):
        """Clear from cursor to end of line, placing into cut buffer"""
        if self.is_end_of_the_line:
            pass
        else:
            self.cut_buffer.append(self.s[-self.cpos:])
            self.s = self.s[:-self.cpos]
            self.cpos = 0
            self.print_line(self.s, clr=True)

    def backward_kill_line(self):
        """Clear from cursor to beginning of line, placing into cut buffer"""
        if self.is_end_of_the_line:
            if self.s:
                self.cut_buffer.append(self.s)
            else:
                pass
        else:
            self.cut_buffer.append(self.s[:-self.cpos])
        self.clear_wrapped_lines()
        if not self.cpos:
            self.s = ''
        else:
            self.s = self.s[-self.cpos:]
        self.cpos = len(self.s)
        self.print_line(self.s, clr=True)

    def beginning_of_line(self, refresh=True):
        self.scr.move(self.iy, self.ix)
        self.cpos = len(self.s)
        if refresh:
            self.scr.refresh()

    def end_of_line(self, refresh=True):
        self.cpos = 0
        s_width = list(map(self._get_width, self.s))
        h, w = App.gethw()
        y, x = divmod(sum(s_width) + self.ix, w)
        y += self.iy
        self.scr.move(y, x)
        if refresh:
            self.scr.refresh()

    def yank(self):
        """Paste the text from the cut buffer at the current cursor location"""
        if len(self.cut_buffer) > 0:
            self.addstr(self.cut_buffer[-1])
            self.print_line(self.s, clr=True)

    def yank_pop(self, yank_index):
        """Paste the text from the cut buffer at the current cursor location"""
        if len(self.cut_buffer) > 0:
            for _ in xrange(len(self.cut_buffer[(yank_index + 1) % len(self.cut_buffer)])):
                self.backward_delete_character()
            self.addstr(self.cut_buffer[yank_index % len(self.cut_buffer)])
            self.print_line(self.s, clr=True)

    def accept_line(self):
        """Process a linefeed character; it only needs to check the
        cursor position and move appropriately so it doesn't clear
        the current line after the cursor."""
        if self.cpos:
            for _ in xrange(self.cpos):
                self.mvc(-1)

        # Reprint the line (as there was maybe a highlighted paren in it)
        self.print_line(self.s, newline=True)
        self.echo("\n")


class CLIRepl(repl.Repl, Editable):
    def __init__(self, scr, interp, config):
        repl.Repl.__init__(self, interp, config)
        Editable.__init__(self, scr, config)
        self.interp.writetb = self.writetb
        self.exit_value = ()
        self.f_string = ''
        self.skip_completion = False
        self.in_hist = False
        self.in_search_mode = None
        self.rl_indices = []
        self.formatter = BPythonFormatter(config.color_scheme)
        self.interact = CLIInteraction(config, statusbar=app.statusbar)

        self.list_box = ListBox(app.newwin(1, 1, 1, 1), config, format_docstring=self.format_docstring)

    @property
    def current_line(self):
        """Return the current line."""
        return self.s

    def clear_current_line(self):
        """Called when a SyntaxError occured in the interpreter. It is
        used to prevent autoindentation from occuring after a
        traceback."""
        self.s = ''

    def addstr(self, s):
        """Add a string to the current input line and figure out
        where it should go, depending on the cursor position."""
        Editable.addstr(self, s)
        self.matches_iter.reset()
        self.complete()

    def accept_line(self):
        Editable.accept_line(self)
        self.rl_history.reset()
        self.in_search_mode = None
        app.statusbar.refresh()

    def backward_delete_character(self, delete_tabs=True):
        """Process a backspace"""
        result = Editable.backward_delete_character(self, delete_tabs=delete_tabs)
        self.matches_iter.reset()
        self.complete()
        return result

    def backward_kill_word(self):
        self.skip_completion = True
        Editable.backward_kill_word(self)
        self.skip_completion = False
        self.complete()

    def backward_kill_line(self):
        Editable.backward_kill_line(self)
        self.complete()
        self.scr.redrawwin()
        self.scr.refresh()

    def get_line(self):
        """Get a line of text and return it
        This function initialises an empty string and gets the
        curses cursor position on the screen and stores it
        for the echo() function to use later (I think).
        Then it waits for key presses and passes them to p_key(),
        which returns None if Enter is pressed (that means "Return",
        idiot)."""
        self.s = ''
        self.iy, self.ix = self.scr.getyx()
        if not self.paste_mode:
            for _ in xrange(self.next_indentation()):
                self.p_key('\t')
        self.cpos = 0
        Editable.get_line(self)
        if self.config.cli_trim_prompts and self.s.startswith(self.ps1):
            self.s = self.s[len(self.ps1):]
        return self.s

    def complete(self, tab=False):
        """Get Autcomplete list and window."""
        if self.skip_completion:
            return
        if self.in_search_mode == "search":
            self.search_history()
        elif self.in_search_mode == "reverse":
            self.reverse_search_history()
        elif self.paste_mode:
            if self.list_win_visible:
                self.scr.touchwin()
        elif self.list_win_visible and not self.config.auto_display_list:
            self.scr.touchwin()
            self.list_win_visible = False
            self.matches_iter.update()
        elif self.config.auto_display_list or tab:
            self.list_win_visible = repl.Repl.complete(self, tab)
            if self.list_win_visible:
                try:
                    self.reset_and_show_list_box()
                except curses.error:
                    # XXX: This is a massive hack, it will go away when I get
                    # cusswords into a good enough state that we can start
                    # using it.
                    self.list_box.refresh()
                    self.list_win_visible = False
            if not self.list_win_visible:
                self.scr.redrawwin()
                self.scr.refresh()

    def beginning_of_history(self):
        """Replace the active line with first line in history and
        increment the index to keep track"""
        self.cpos = 0
        self.clear_wrapped_lines()
        self.s = self.rl_history.first()
        self.print_line(self.s, clr=True)

    def end_of_history(self):
        """Same as hbegin() but, well, forward"""
        self.cpos = 0
        self.clear_wrapped_lines()
        self.rl_history.last()
        self.s = ""
        self.print_line(self.s, clr=True)

    def insert_last_argument(self):
        self.cpos = 0
        self.clear_wrapped_lines()
        self.rl_history.enter(self.s)
        s = self.rl_history.back().rstrip().split()[-1]
        self.addstr(s)

    def previous_history(self):
        """Replace the active line with previous line in history and
        increment the index to keep track"""

        self.cpos = 0
        self.clear_wrapped_lines()
        self.rl_history.enter(self.s)
        self.s = self.rl_history.back()
        #        self.print_line(self.s, clr=True)
        self.exit_search_mode()

    def next_history(self):
        """Same as back() but, well, forward"""
        self.cpos = 0
        self.clear_wrapped_lines()
        self.rl_history.enter(self.s)
        self.s = self.rl_history.forward()
        #        self.print_line(self.s, clr=True)
        self.exit_search_mode()

    def reverse_search_history(self):
        """Search with the partial matches from the history object."""
        self.clear_wrapped_lines()
        self.rl_history.enter(self.s)
        index = self.rl_history.index
        self.matches = []
        self.rl_indices = []
        for m, i in self.rl_history.back_iter(start=False, search=True):
            self.matches.append(m)
            self.rl_indices.append(i)
        self.rl_history.index = index
        self.matches_iter.update(self.s, self.matches)

        if self.s and len(self.matches) > 0:
            self.print_line(self.s, clr=True)
            try:
                self.reset_and_show_list_box(nosep=True)
            except curses.error:
                # XXX: This is a massive hack, it will go away when I get
                # cusswords into a good enough state that we can start
                # using it.
                self.list_box.refresh()
                self.list_win_visible = False
        else:
            self.list_win_visible = False
            self.redraw()

        self.interact.notify("mode: %s" % "reverse-search")
        self.in_search_mode = "reverse"

    def search_history(self):
        """Search with the partial matches from the history object."""
        self.clear_wrapped_lines()
        self.rl_history.enter(self.s)
        index = self.rl_history.index
        self.matches = []
        self.rl_indices = []
        for m, i in self.rl_history.forward_iter(start=False, search=True):
            self.matches.append(m)
            self.rl_indices.append(i)
        self.rl_history.index = index
        self.matches_iter.update(self.s, self.matches)

        if self.s and len(self.matches) > 0:
            self.print_line(self.s, clr=True)
            try:
                self.reset_and_show_list_box(nosep=True)
            except curses.error:
                # XXX: This is a massive hack, it will go away when I get
                # cusswords into a good enough state that we can start
                # using it.
                self.list_box.refresh()
                self.list_win_visible = False
        else:
            self.list_win_visible = False
            self.redraw()

        self.interact.notify("mode: %s" % "search")
        self.in_search_mode = "search"

    def exit_search_mode(self):
        self.in_search_mode = None
        self.redraw()

    def prompt(self, more):
        """Show the appropriate Python prompt"""
        self.stdout_history.append_raw("")
        if not more:
            self.echo("\x01%s\x03%s" % (self.config.color_scheme['prompt'], self.ps1))
            self.stdout_history[-1] += self.ps1
            self.s_hist.append('\x01%s\x03%s\x04' %
                               (self.config.color_scheme['prompt'], self.ps1))
        else:
            prompt_more_color = self.config.color_scheme['prompt_more']
            self.echo("\x01%s\x03%s" % (prompt_more_color, self.ps2))
            self.stdout_history[-1] += self.ps2
            self.s_hist.append('\x01%s\x03%s\x04' % (prompt_more_color, self.ps2))

    def push(self, s, insert_into_history=True):
        # curses.raw(True) prevents C-c from causing a SIGINT
        curses.raw(False)
        try:
            return repl.Repl.push(self, s, insert_into_history)
        except SystemExit as e:
            # Avoid a traceback on e.g. quit()
            self.do_exit = True
            self.exit_value = e.args
            return False
        finally:
            curses.raw(True)

    def run(self):
        """Initialise the repl and jump into the loop. This method also has to
        keep a stack of lines entered for the horrible "undo" feature. It also
        tracks everything that would normally go to stdout in the normal Python
        interpreter so it can quickly write it to stdout on exit after
        curses.endwin(), as well as a history of lines entered for using
        up/down to go back and forth (which has to be separate to the
        evaluation history, which will be truncated when undoing."""

        # Use our own helper function because Python's will use real stdin and
        # stdout instead of our wrapped
        self.push('from bpython._internal import _help as help\n', False)
        self.iy, self.ix = self.scr.getyx()
        more = False
        while not self.do_exit:
            self.f_string = ''
            self.prompt(more)
            try:
                inp = self.get_line()
            except KeyboardInterrupt:
                app.statusbar.message('KeyboardInterrupt')
                self.scr.addstr('\n')
                self.scr.touchwin()
                self.scr.refresh()
                continue

            self.scr.redrawwin()
            if self.do_exit:
                return self.exit_value

            self.history.append(inp)
            self.s_hist[-1] += self.f_string
            if PY3:
                self.stdout_history[-1] += inp
            else:
                self.stdout_history[-1] += inp.encode(getpreferredencoding())
            more = self.push(inp)
            if not more:
                self.s = ''
        return self.exit_value

    def redraw(self):
        """Redraw the screen."""
        self.scr.erase()
        for k, s in enumerate(self.s_hist):
            if not s:
                continue
            self.iy, self.ix = self.scr.getyx()
            for i in s.split('\x04'):
                self.echo(i, redraw=False)
            if k < len(self.s_hist) - 1:
                self.scr.addstr('\n')
        self.iy, self.ix = self.scr.getyx()
        self.print_line(self.s)
        app.refresh()

    def resize(self):
        """This method exists simply to keep it straight forward when
        initialising a window and resizing it."""
        self.size()
        self.scr.erase()
        self.scr.resize(self.h, self.w)
        self.scr.mvwin(self.y, self.x)
        app.statusbar.resize(refresh=False)
        self.redraw()

    def reevaluate(self):
        """Clear the buffer, redraw the screen and re-evaluate the history"""
        self.evaluating = True
        self.stdout_history.entries = []
        self.f_string = ''
        self.buffer = []
        self.scr.erase()
        self.s_hist = []
        # Set cursor position to -1 to prevent paren matching
        self.cpos = -1

        self.prompt(False)

        self.iy, self.ix = self.scr.getyx()
        for line in self.history:
            if PY3:
                self.stdout_history[-1] += line
            else:
                self.stdout_history[-1] += line.encode(getpreferredencoding())
            self.print_line(line)
            self.s_hist[-1] += self.f_string
            # I decided it was easier to just do this manually
            # than to make the print_line and history stuff more flexible.
            self.scr.addstr('\n')
            more = self.push(line)
            self.prompt(more)
            self.iy, self.ix = self.scr.getyx()

        self.cpos = 0
        indent = repl.next_indentation(self.s, self.config.tab_length)
        self.s = ''
        self.scr.refresh()

        if self.buffer:
            for _ in xrange(indent):
                self.tab()

        self.evaluating = False
        #map(self.push, self.history)
        #^-- That's how simple this method was at first :(

    def write(self, s):
        """For overriding stdout defaults"""
        if '\x04' in s:
            for block in s.split('\x04'):
                self.write(block)
            return
        if s.rstrip() and '\x03' in s:
            t = s.split('\x03')[1]
        else:
            t = s

        if not PY3 and isinstance(t, unicode):
            t = t.encode(getpreferredencoding())

        self.stdout_history.append(t)

        self.echo(s)
        self.s_hist.append(s.rstrip())

    def reset_and_show_list_box(self, nosep=False):
        self.list_box.reset_with(self, nosep)
        self.show_list_box()

    def show_list_box(self):
        self.list_box.show()
        app.statusbar.scr.touchwin()
        app.statusbar.scr.noutrefresh()
        self.scr.touchwin()
        self.scr.cursyncup()
        self.scr.noutrefresh()

        # This looks a little odd, but I can't figure a better way to stick the cursor
        # back where it belongs (refreshing the window hides the list_win)

        self.scr.move(*self.scr.getyx())
        self.list_box.refresh()

    def show_next_page(self):
        self.list_box.next_page(self.matches_iter)
        app.statusbar.scr.touchwin()
        app.statusbar.scr.noutrefresh()
        app.clirepl.scr.touchwin()
        app.clirepl.scr.cursyncup()
        app.clirepl.scr.noutrefresh()
        app.clirepl.scr.move(*app.clirepl.scr.getyx())
        self.list_box.refresh()

    def size(self):
        """Set instance attributes for x and y top left corner coordinates
        and width and heigth for the window."""
        h, w = app.scr.getmaxyx()
        self.x = 0
        self.y = 0
        self.w = w
        self.h = h - 1

    def clear_screen(self):
        self.s_hist = [self.s_hist[-1]]
        self.highlighted_paren = None
        self.in_search = None
        self.redraw()

    def suspend(self):
        """Suspend the current process for shell job control."""
        if platform.system() != 'Windows':
            curses.endwin()
            os.kill(os.getpid(), signal.SIGSTOP)
            return ''
        else:
            self.do_exit = True
            return None

    def tab(self, back=False):
        """Process the tab key being hit.

        If there's only whitespace
        in the line or the line is blank then process a normal tab,
        otherwise attempt to autocomplete to the best match of possible
        choices in the match list.

        If `back` is True, walk backwards through the list of suggestions
        and don't indent if there are only whitespace in the line.
        """

        mode = self.config.autocomplete_mode

        # 1. check if we should add a tab character
        if self.is_start_of_the_line and not back:
            x_pos = len(self.s) - self.cpos
            num_spaces = x_pos % self.config.tab_length
            if not num_spaces:
                num_spaces = self.config.tab_length

            self.addstr(' ' * num_spaces)
            self.print_line(self.s)
            return True

        # 2. get the current word
        if not self.matches_iter:
            self.complete(tab=True)
            if not self.config.auto_display_list and not self.list_win_visible:
                return True

            sb_expr, sb_attr = self.get_current_sbracket()
            if sb_expr:
                current_word = sb_attr
            else:
                current_word = self.current_string or self.current_word

            if not current_word:
                return True
        else:
            current_word = self.matches_iter.current_word
            # current_word = self.matches_iter.current()

        # 3. check to see if we can expand the current word
        cseq = None
        if mode == completer.SUBSTRING:
            if all([len(match.split(current_word)) == 2 for match in self.matches]):
                seq = [current_word + match.split(current_word)[1] for match in self.matches]
                cseq = os.path.commonprefix(seq)
        else:
            seq = self.matches
            cseq = os.path.commonprefix(seq)

        if cseq and mode != completer.FUZZY:
            expanded_string = cseq[len(current_word):]
            self.s += expanded_string
            expanded = bool(expanded_string)
            self.print_line(self.s)
            if len(self.matches) == 1 and self.config.auto_display_list:
                self.scr.touchwin()
            if expanded:
                self.matches_iter.update(cseq, self.matches)
        else:
            expanded = False

        # 4. swap current word for a match list item
        if not expanded and self.matches:
            # reset s if this is the nth result
            if self.matches_iter:
                if self.cpos:
                    self.s = self.s[:-len(self.matches_iter.current())-self.cpos] + current_word + self.s[-self.cpos:]
                else:
                    self.s = self.s[:-len(self.matches_iter.current())] + current_word

            if back:
                current_match = self.matches_iter.previous()
            else:
                current_match = self.matches_iter.next()

            self.list_box.sync(self.matches_iter)

            if self.in_search_mode:
                self.rl_history.index = self.rl_indices[self.matches_iter.index]

            # update s with the new match
            if current_match:
                if self.config.autocomplete_mode == completer.SIMPLE:
                    self.s += current_match[len(current_word):]
                elif self.in_search_mode:
                    self.s = current_match
                else:
                    if self.cpos:
                        self.s = self.s[:-len(current_word)-self.cpos] + current_match + self.s[-self.cpos:]
                    else:
                        self.s = self.s[:-len(current_word)] + current_match
                try:
                    if self.in_search_mode:
                        self.list_box.nosep = True
                        self.show_list_box()
                    elif self.current_string:
                        self.reset_and_show_list_box(nosep=True)
                    else:
                        self.set_argspec()
                        self.reset_and_show_list_box()
                except curses.error:
                    # XXX: This is a massive hack, it will go away when I get
                    # cusswords into a good enough state that we can start
                    # using it.
                    self.list_box.refresh()


                self.print_line(self.s, True)
        return True

    def undo(self, n=1):
        repl.Repl.undo(self, n)

        # This will unhighlight highlighted parens
        self.print_line(self.s)

    def writetb(self, lines):
        for line in lines:
            self.write('\x01%s\x03%s' % (self.config.color_scheme['error'],
                                         line))


class Statusbar(Editable):
    """This class provides the status bar at the bottom of the screen.
    It has message() and prompt() methods for user interactivity, as
    well as settext() and clear() methods for changing its appearance.

    The check() method needs to be called repeatedly if the statusbar is
    going to be aware of when it should update its display after a message()
    has been called (it'll display for a couple of seconds and then disappear).

    It should be called as:
        foo = Statusbar(scr, 'Initial text to display')
    or, for a blank statusbar:
        foo = Statusbar(scr)

    It can also receive the argument 'c' which will be an integer referring
    to a curses colour pair, e.g.:
        foo = Statusbar(scr, 'Hello', c=4)

    stdscr should be a curses window object in which to put the status bar.
    pwin should be the parent window. To be honest, this is only really here
    so the cursor can be returned to the window properly.

    """

    def __init__(self, scr, config, color=None):
        """Initialise the statusbar and display the initial text (if any)"""
        Editable.__init__(self, scr, config)
        self.size()

        self.s = ''
        self._s = config.statusbar_text
        self.c = color
        self.timer = 0
        self.settext(self._s, color)

    def size(self):
        """Set instance attributes for x and y top left corner coordinates
        and width and heigth for the window."""
        h, w = App.gethw()
        y, x = app.scr.getyx()
        self.h = 1
        self.w = w
        self.y = h - 1
        self.x = 0

    def resize(self, refresh=True):
        """This method exists simply to keep it straight forward when
        initialising a window and resizing it."""
        self.size()
        self.scr.mvwin(self.y, self.x)
        self.scr.resize(self.h, self.w)
        if refresh:
            self.refresh()

    def refresh(self):
        """This is here to make sure the status bar text is redraw properly
        after a resize."""
        self.settext(self._s)

    def check(self):
        """This is the method that should be called every half second or so
        to see if the status bar needs updating."""
        if not self.timer:
            return

        if time.time() < self.timer:
            return

        self.settext(self._s)

    def message(self, s, n=3):
        """Display a message for a short n seconds on the statusbar and return
        it to its original state."""
        self.timer = time.time() + n
        self.settext(s)

    def prompt(self, s=''):
        """Prompt the user for some input (with the optional prompt 's') and
        return the input text, then restore the statusbar to its original
        value."""

        self.settext(s or '? ', p=True)
        self.iy, self.ix = self.scr.getyx()

        result = self.get_line()
        self.settext(self._s)
        return result

    #        return o

    def settext(self, s, c=None, p=False):
        """Set the text on the status bar to a new permanent value; this is the
        value that will be set after a prompt or message. c is the optional
        curses colour pair to use (if not specified the last specified colour
        pair will be used).  p is True if the cursor is expected to stay in the
        status window (e.g. when prompting)."""

        self.scr.erase()
        if len(s) >= self.w:
            s = s[:self.w - 1]

        self.s = ""
        if c:
            self.c = c

        if s:
            if not PY3 and isinstance(s, unicode):
                s = s.encode(getpreferredencoding())

            if self.c:
                self.scr.addstr(s, self.c)
            else:
                self.scr.addstr(s)

        if not p:
            self.scr.noutrefresh()
            if hasattr(app, 'clirepl'):
                app.clirepl.scr.refresh()
        else:
            self.scr.refresh()

    def clear(self):
        """Clear the status bar."""
        self.scr.clear()


class App(object):
    DO_RESIZE = False

    def __init__(self, scr, locals_, config):
        global app
        app = bpython.running = self

        self.scr = scr
        self.config = config

        self.set_colors()
        main_win, status_win = self.init_wins()

        self.statusbar = Statusbar(status_win, self.config, color=app.get_colpair('main'))

        if locals_ is None:
            sys.modules['__main__'] = ModuleType('__main__')
            locals_ = sys.modules['__main__'].__dict__
        self.interpreter = BPythonInterpreter(locals_, getpreferredencoding())

        self.clirepl = CLIRepl(main_win, self.interpreter, config)
        self.clirepl._C = self.colors

    def __enter__(self):
        if platform.system() != 'Windows':
            self.old_sigwinch_handler = signal.signal(signal.SIGWINCH,
                                                      lambda *_: App.sigwinch(self.scr))
            # redraw window after being suspended
            self.old_sigcont_handler = signal.signal(signal.SIGCONT, lambda *_: App.sigcont(self.scr))

        sys.stdin = FakeStdin(self.clirepl)
        sys.stdout = FakeStream(self.clirepl)
        sys.stderr = FakeStream(self.clirepl)

        curses.raw(True)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.clirepl.scr.clear()
        self.clirepl.scr.refresh()
        self.statusbar.scr.clear()
        self.statusbar.scr.refresh()
        curses.raw(False)

        sys.stdin = sys.__stdin__
        sys.stderr = sys.__stderr__
        sys.stdout = sys.__stdout__

        # Restore signal handlers
        if platform.system() != 'Windows':
            signal.signal(signal.SIGWINCH, self.old_sigwinch_handler)
            signal.signal(signal.SIGCONT, self.old_sigcont_handler)

    def register_command(self, name, function=None, without_completion=False):
        return self.clirepl.register_command(name, function, without_completion)

    def set_handler_on(self, ambiguous_keyname, function=None):
        from bpython.key.dispatch_table import dispatch_table
        return dispatch_table.set_handler_on(ambiguous_keyname, function)

    def set_handler_on_clirepl(self, ambiguous_keyname, function=None):
        from bpython.key.dispatch_table import dispatch_table
        return dispatch_table.set_handler_on_clirepl(ambiguous_keyname, function)

    def set_handler_on_statusbar(self, ambiguous_keyname, function=None):
        from bpython.key.dispatch_table import dispatch_table
        return dispatch_table.set_handler_on_statusbar(ambiguous_keyname, function)

    def newwin(self, *args):
        """Wrapper for curses.newwin to automatically set background colour on any
        newly created window."""
        background = app.get_colpair('background')
        win = curses.newwin(*args)
        win.bkgd(' ', background)
        win.scrollok(True)
        win.keypad(1)
        # Thanks to Angus Gibson for pointing out this missing line which was causing
        # problems that needed dirty hackery to fix. :)
        return win

    @staticmethod
    def sigwinch(unused_scr):
        App.DO_RESIZE = True

    @staticmethod
    def sigcont(unused_scr):
        App.sigwinch(unused_scr)
        # Forces the redraw
        curses.ungetch('\x00')

    @staticmethod
    def gethw():
        """I found this code on a usenet post, and snipped out the bit I needed,
        so thanks to whoever wrote that, sorry I forgot your name, I'm sure you're
        a great guy.

        It's unfortunately necessary (unless someone has any better ideas) in order
        to allow curses and readline to work together. I looked at the code for
        libreadline and noticed this comment:

            /* This is the stuff that is hard for me.  I never seem to write good
               display routines in C.  Let's see how I do this time. */

        So I'm not going to ask any questions.

        """

        if platform.system() != 'Windows':
            h, w = struct.unpack(
                "hhhh",
                fcntl.ioctl(sys.__stdout__, termios.TIOCGWINSZ, "\000" * 8))[0:2]
        else:
            from ctypes import windll, create_string_buffer

            # stdin handle is -10
            # stdout handle is -11
            # stderr handle is -12

            h = windll.kernel32.GetStdHandle(-12)
            csbi = create_string_buffer(22)
            res = windll.kernel32.GetConsoleScreenBufferInfo(h, csbi)

            if res:
                (bufx, bufy, curx, cury, wattr,
                 left, top, right, bottom, maxx, maxy) = struct.unpack("hhhhHhhhhhh", csbi.raw)
                sizex = right - left + 1
                sizey = bottom - top + 1
            else:
                sizex, sizey = app.scr.getmaxyx()# can't determine actual size - return default values

            h, w = sizey, sizex
        return h, w

    @staticmethod
    def idle(caller):
        """This is called once every iteration through the getkey()
        loop (currently in the Repl class, see the get_line() method).
        The statusbar check needs to go here to take care of timed
        messages and the resize handlers need to be here to make
        sure it happens conveniently."""

        if import_completer.find_coroutine() or caller.paste_mode:
            caller.scr.nodelay(True)
            key = caller.scr.getch()
            caller.scr.nodelay(False)
            if key != -1:
                curses.ungetch(key)
            else:
                curses.ungetch('\x00')

                app.statusbar.check()
        caller.check()

        if App.DO_RESIZE:
            App.do_resize(caller)

    @staticmethod
    def do_resize(caller):
        """This needs to hack around readline and curses not playing
        nicely together. See also gethw() above."""
        h, w = App.gethw()
        if not h:
        # Hopefully this shouldn't happen. :)
            return

        curses.endwin()
        os.environ["LINES"] = str(h)
        os.environ["COLUMNS"] = str(w)
        curses.doupdate()
        App.DO_RESIZE = False

        caller.resize()
        # The list win resizes itself every time it appears so no need to do it here.

    def init_wins(self):
        """Initialise the two windows (the main repl interface and the little
        status bar at the bottom with some stuff in it)"""

        self.scr.timeout(300)

        h, w = App.gethw()

        main_win = app.newwin(h - 1, w, 0, 0)
        status_win = app.newwin(1, w, h - 1, 0)
        return main_win, status_win

    def set_colors(self):
        try:
            # curses.start_color()
            curses.use_default_colors()
            cols = self._make_colors()
        except curses.error:
            cols = FakeDict(-1)

        self.colors = cols

    def get_colpair(self, name):
        color = self.colors[self.config.color_scheme[name].lower()]
        return curses.color_pair(color + 1)

    def _make_colors(self):
        """Init all the colours in curses and bang them into a dictionary"""

        # blacK, Red, Green, Yellow, Blue, Magenta, Cyan, White, Default:
        c = {
            'k': 0,
            'r': 1,
            'g': 2,
            'y': 3,
            'b': 4,
            'm': 5,
            'c': 6,
            'w': 7,
            'd': -1,
        }

        if platform.system() == 'Windows':
            c = dict(c.items() +
                     [
                         ('K', 8),
                         ('R', 9),
                         ('G', 10),
                         ('Y', 11),
                         ('B', 12),
                         ('M', 13),
                         ('C', 14),
                         ('W', 15),
                     ]
            )

        for i in xrange(63):
            if i > 7:
                j = i // 8
            else:
                j = c[self.config.color_scheme['background']]
            curses.init_pair(i + 1, i % 8, j)

        return c

    @property
    def stdout(self):
        return self.clirepl.stdout

    def refresh(self):
        self.clirepl.scr.refresh()
        self.statusbar.refresh()

    def run(self, args, interactive, banner):
        if args:
            exit_value = 0
            try:
                bpython.config.args.exec_code(self.interpreter, args)
            except SystemExit as e:
                # The documentation of code.InteractiveInterpreter.runcode claims
                # that it reraises SystemExit. However, I can't manage to trigger
                # that. To be one the safe side let's catch SystemExit here anyway.
                exit_value = e.args
            if not interactive:
                return exit_value
        else:
            sys.path.insert(0, '')
            self.clirepl.startup()

        if banner is not None:
            self.clirepl.write(banner)
            self.clirepl.write('\n')
        exit_value = self.clirepl.run()
        return exit_value


def main_curses(scr, args, config, interactive=True, locals_=None,
                banner=None):
    """main function for the curses convenience wrapper

    Initialise the two main objects: the interpreter
    and the repl. The repl does what a repl does and lots
    of other cool stuff like syntax highlighting and stuff.
    I've tried to keep it well factored but it needs some
    tidying up, especially in separating the curses stuff
    from the rest of the repl.

    Returns a tuple (exit value, output), where exit value is a tuple
    with arguments passed to SystemExit.
    """
    with App(scr, locals_, config) as app:
        exit_value = app.run(args, interactive, banner)
        return (exit_value, app.stdout)


def main(args=None, locals_=None, banner=None):
    translations.init()
    config, options, exec_args = bpython.config.args.parse_and_load(bpython.config.config, args)

    (exit_value, output) = curses.wrapper(
        main_curses, exec_args, config, options.interactive, locals_,
        banner=banner)

    # Fake stdout data so everything's still visible after exiting
    if config.flush_output and not options.quiet:
        sys.stdout.write(output)
    if hasattr(sys.stdout, 'flush'):
        sys.stdout.flush()
    return repl.extract_exit_value(exit_value)


if __name__ == '__main__':
    sys.exit(main())

# vim: sw=4 ts=4 sts=4 ai et
