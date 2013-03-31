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
if platform.system() != 'Windows':
    import signal      #Windows does not have job control
    import termios     #Windows uses curses
    import fcntl       #Windows uses curses
import unicodedata
import errno

import locale
from types import ModuleType

# These are used for syntax highlighting
from pygments import format
from pygments.token import Token
from bpython.formatter import BPythonFormatter

# This for completion
from bpython.completion import importcompletion
from bpython.completion import autocomplete

# This for config
from bpython.config.struct import Struct

# This for i18n
from bpython import translations
from bpython.translations import _

from bpython import repl
from bpython._py3compat import PythonLexer, py3
from bpython.formatter import Parenthesis
import bpython.config.args

if not py3:
    import inspect


# --- module globals ---
app = None

# ---


def getpreferredencoding():
    return locale.getpreferredencoding() or sys.getdefaultencoding()

def calculate_screen_lines(tokens, width, cursor=0):
    """Given a stream of tokens and a screen width plus an optional
    initial cursor position, return the amount of needed lines on the
    screen."""
    lines = 1
    pos = cursor
    for (token, value) in tokens:
        if token is Token.Text and value == '\n':
            lines += 1
        else:
            pos += len(value)
            lines += pos // width
            pos %= width
    return lines


class FakeStream(object):
    """Provide a fake file object which calls functions on the interface
    provided."""

    def __init__(self, interface):
        self.encoding = getpreferredencoding()
        self.interface = interface

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

        if py3:
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


# TODO:
#
# Tab completion does not work if not at the end of the line.
#
# Numerous optimisations can be made but it seems to do all the lookup stuff
# fast enough on even my crappy server so I'm not too bothered about that
# at the moment.
#
# The popup window that displays the argspecs and completion suggestions
# needs to be an instance of a ListWin class or something so I can wrap
# the addstr stuff to a higher level.
#


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


class Editable(object):
    def __init__(self, scr, config):
        from bpython.key.dispatcher import Dispatcher
        self.scr = scr
        self.config = config
        self.s = ''
        self.cut_buffer = []
        self.cpos = 0
        self.do_exit = False
        self.last_key_press = time.time()
        self.paste_mode = False
        self.idle = App.idle
        self.highlighted_paren = None
        self.key_dispatcher = Dispatcher(self)
        self.iy, self.ix = self.scr.getyx()

    def _get_width(self,  c):
        if unicodedata.east_asian_width(c) in 'WFA':
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
                if py3:
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
#                if self.config.cli_trim_prompts and self.s.startswith(self.ps1):
#                    self.s = self.s[4:]
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

        if self.cpos == 0 and i < 0:
            return False

        if x == self.ix and y == self.iy and i >= 1:
            return False

        s_width = list(map(self._get_width, self.s))
        width = 0
        if i > 0:
            if i == 1:
                width = s_width[- self.cpos - 1]
            else:
                for _ in range(i):
                    self.mvc(1)
        elif i == 0:
            return False
        else:
            if i == -1:
                width = - s_width[- self.cpos]
            else:
                for _ in range(-i):
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
#        if self.cpos == 0:
#            self.interact.notify(u"width: %s cpos: %s current_w: %d i: %d" % ( unicode(s_width), unicode(self.cpos), 0, i) )
#        else:
#            try:
#                self.interact.notify(u"width: %s cpos: %s current_w: %d i: %d" % ( unicode(s_width), unicode(self.cpos), s_width[- self.cpos], i) )
#            except:
#                self.interact.notify(u"width: %s cpos: %s current_w: %d i: %d" % ( unicode(s_width), unicode(self.cpos), 0, i) )

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

    def is_beginning_of_the_line(self):
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
        if not py3 and isinstance(s, unicode):
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
            for _ in range(t):
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
        if self.cpos == 0 and not self.s:
            pass
        else:
            pos = len(self.s) - self.cpos - 1
            while pos >= 0 and self.s[pos] == ' ':
                pos -= 1
                self.backward_character()
                # Then we delete a full word.
            while pos >= 0 and self.s[pos] != ' ':
                pos -= 1
                self.backward_character()

    def forward_word(self):
        if self.cpos == 0 and not self.s:
            pass
        else:
            len_s = len(self.s)
            pos = len_s - self.cpos - 1
            while len_s > pos and self.s[pos] == ' ':
                pos += 1
                self.forward_character()
                # Then we delete a full word.
            while len_s > pos and self.s[pos] != ' ':
                pos += 1
                self.forward_character()

    def backward_delete_character(self, delete_tabs=True):
        """Process a backspace"""
        y, x = self.scr.getyx()
        if not self.s:
            return
        if x == self.ix and y == self.iy:
            return
        n = 1
        self.clear_wrapped_lines()
        if not self.cpos:
            # I know the nested if blocks look nasty. :(
            if self.is_beginning_of_the_line() and delete_tabs:
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
        if not self.s:
            return

        if self.mvc(-1):
            self.backward_delete_character(False)

    def kill_word(self):
        if self.cpos == 0 and not self.s:
            pass
        else:
            deleted = []
            len_s = len(self.s)
            pos = len_s - self.cpos
            while self.cpos > 0 and self.s[pos] == ' ':
                deleted.append(self.s[pos])
                self.delete_character()
                # Then we delete a full word.
            while self.cpos > 0 and self.s[pos] != ' ':
                deleted.append(self.s[pos])
                self.delete_character()
            self.cut_buffer.append(''.join(deleted))

    def backward_kill_word(self):
        if self.cpos == 0 and not self.s:
            pass
        else:
            pos = len(self.s) - self.cpos - 1
            deleted = []
            # First we delete any space to the left of the cursor.
            while pos >= 0 and self.s[pos] == ' ':
                deleted.append(self.s[pos])
                pos -= self.backward_delete_character()
                # Then we delete a full word.
            while pos >= 0 and self.s[pos] != ' ':
                deleted.append(self.s[pos])
                pos -= self.backward_delete_character()
            self.cut_buffer.append(''.join(reversed(deleted)))

    def kill_line(self):
        """Clear from cursor to end of line, placing into cut buffer"""
        if self.cpos == 0:
            pass
        else:
            self.cut_buffer.append(self.s[-self.cpos:])
            self.s = self.s[:-self.cpos]
            self.cpos = 0
            self.print_line(self.s, clr=True)

    def backward_kill_line(self):
        """Clear from cursor to beginning of line, placing into cut buffer"""
        if self.cpos == 0:
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
        self.addstr(self.cut_buffer[-1])
        self.print_line(self.s, clr=True)

    def yank_pop(self, yank_index):
        """Paste the text from the cut buffer at the current cursor location"""
        for _ in range(len(self.cut_buffer[(yank_index + 1) % len(self.cut_buffer)])):
            self.backward_delete_character()
        self.addstr(self.cut_buffer[yank_index % len(self.cut_buffer)])
        self.print_line(self.s, clr=True)

    def accept_line(self):
        """Process a linefeed character; it only needs to check the
        cursor position and move appropriately so it doesn't clear
        the current line after the cursor."""
        if self.cpos:
            for _ in range(self.cpos):
                self.mvc(-1)

        # Reprint the line (as there was maybe a highlighted paren in it)
        self.print_line(self.s, newline=True)
        self.echo("\n")


class CLIRepl(repl.Repl, Editable):
    def __init__(self, scr, interp, config):
        repl.Repl.__init__(self, interp, config)
        Editable.__init__(self, scr, config)
        self.interp.writetb = self.writetb
        self.list_win = app.newwin(1, 1, 1, 1)
        self.exit_value = ()
        self.f_string = ''
        self.in_hist = False
        self.formatter = BPythonFormatter(config.color_scheme)
        self.interact = CLIInteraction(self.config, statusbar=app.statusbar)

        if config.cli_suggestion_width <= 0 or config.cli_suggestion_width > 1:
            config.cli_suggestion_width = 0.8

    def current_line(self):
        """Return the current line."""
        return self.s

    def clear_current_line(self):
        """Called when a SyntaxError occured in the interpreter. It is
        used to prevent autoindentation from occuring after a
        traceback."""
        self.s = ''

    def current_word(self):
        """Return the current word, i.e. the (incomplete) word directly to the
        left of the cursor"""

        # I don't know if autocomplete should be disabled if the cursor
        # isn't at the end of the line, but that's what this does for now.
        if self.cpos: return

        # look from right to left for a bad method character
        l = len(self.s)
        is_method_char = lambda c: c.isalnum() or c in ('.', '_')

        if not self.s or not is_method_char(self.s[l-1]):
            return

        for i in range(1, l+1):
            if not is_method_char(self.s[-i]):
                i -= 1
                break

        return self.s[-i:]

    def addstr(self, s):
        """Add a string to the current input line and figure out
        where it should go, depending on the cursor position."""
        self.rl_history.reset()
        Editable.addstr(self, s)
        self.complete()

    def backward_delete_character(self, delete_tabs=True):
        """Process a backspace"""
        self.rl_history.reset()
        result = Editable.backward_delete_character(self, delete_tabs=delete_tabs)
        self.complete()
        return result

    def backward_kill_word(self):
        self.rl_history.reset()
        result = Editable.backward_kill_word(self)
        self.complete()
        return result

    def backward_kill_line(self):
        Editable.backward_kill_line(self)
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
        self.rl_history.reset()
        self.s = ''
        self.iy, self.ix = self.scr.getyx()
        if not self.paste_mode:
            for _ in xrange(self.next_indentation()):
                self.p_key('\t')
        self.cpos = 0
        return Editable.get_line(self)

    def complete(self, tab=False):
        """Get Autcomplete list and window."""
        if self.paste_mode and self.list_win_visible:
            self.scr.touchwin()

        if self.paste_mode:
            return

        if self.list_win_visible and not self.config.auto_display_list:
            self.scr.touchwin()
            self.list_win_visible = False
            self.matches_iter.update()
            return

        if self.config.auto_display_list or tab:
            self.list_win_visible = repl.Repl.complete(self, tab)
            if self.list_win_visible:
                try:
                    self.show_list(self.matches, self.argspec)
                except curses.error:
                    # XXX: This is a massive hack, it will go away when I get
                    # cusswords into a good enough state that we can start
                    # using it.
                    self.list_win.border()
                    self.list_win.refresh()
                    self.list_win_visible = False
            if not self.list_win_visible:
                self.scr.redrawwin()
                self.scr.refresh()

    def beginning_of_history(self):
        """Replace the active line with first line in history and
        increment the index to keep track"""
        self.cpos = 0
        self.clear_wrapped_lines()
        self.rl_history.enter(self.s)
        self.s = self.rl_history.first()
        self.print_line(self.s, clr=True)

    def end_of_history(self):
        """Same as hbegin() but, well, forward"""
        self.cpos = 0
        self.clear_wrapped_lines()
        self.rl_history.enter(self.s)
        self.s = self.rl_history.last()
        self.print_line(self.s, clr=True)

    def insert_last_argument(self):
        self.cpos = 0
        self.clear_wrapped_lines()
        self.rl_history.enter(self.s)
        self.s = self.rl_history.back().rstrip().split()[-1]
        self.print_line(self.s, clr=True)

    def previous_history(self):
        """Replace the active line with previous line in history and
        increment the index to keep track"""

        self.cpos = 0
        self.clear_wrapped_lines()
        self.rl_history.enter(self.s)
        self.s = self.rl_history.back()
        self.print_line(self.s, clr=True)

    def next_history(self):
        """Same as back() but, well, forward"""

        self.cpos = 0
        self.clear_wrapped_lines()
        self.rl_history.enter(self.s)
        self.s = self.rl_history.forward()
        self.print_line(self.s, clr=True)

    def reverse_search_history(self):
        """Search with the partial matches from the history object."""
        self.cpo = 0
        self.clear_wrapped_lines()
        self.rl_history.enter(self.s)
        self.s = self.rl_history.back(start=False, search=True)
        self.print_line(self.s, clr=True)

    def search_history(self):
        """Search with the partial matches from the history object."""
        self.cpo = 0
        self.clear_wrapped_lines()
        self.rl_history.enter(self.s)
        self.s = self.rl_history.fwd(start=False, search=True)
        self.print_line(self.s, clr=True)

    def mkargspec(self, topline, down):
        """This figures out what to do with the argspec and puts it nicely into
        the list window. It returns the number of lines used to display the
        argspec.  It's also kind of messy due to it having to call so many
        addstr() to get the colouring right, but it seems to be pretty
        sturdy."""

        r = 3
        fn = topline[0]
        args = topline[1][0]
        kwargs = topline[1][3]
        _args = topline[1][1]
        _kwargs = topline[1][2]
        is_bound_method = topline[2]
        in_arg = topline[3]
        if py3:
            kwonly = topline[1][4]
            kwonly_defaults = topline[1][5] or dict()
        max_w = int(self.scr.getmaxyx()[1] * 0.6)
        self.list_win.erase()
        self.list_win.resize(3, max_w)
        h, w = self.list_win.getmaxyx()

        self.list_win.addstr('\n  ')
        self.list_win.addstr(fn,
            app.get_colpair('name') | curses.A_BOLD)
        self.list_win.addstr(': (', app.get_colpair('name'))
        maxh = self.scr.getmaxyx()[0]

        if is_bound_method and isinstance(in_arg, int):
            in_arg += 1

        punctuation_colpair = app.get_colpair('punctuation')

        for k, i in enumerate(args):
            y, x = self.list_win.getyx()
            ln = len(str(i))
            kw = None
            if kwargs and k + 1 > len(args) - len(kwargs):
                kw = repr(kwargs[k - (len(args) - len(kwargs))])
                ln += len(kw) + 1

            if ln + x >= w:
                ty = self.list_win.getbegyx()[0]
                if not down and ty > 0:
                    h += 1
                    self.list_win.mvwin(ty - 1, 1)
                    self.list_win.resize(h, w)
                elif down and h + r < maxh - ty:
                    h += 1
                    self.list_win.resize(h, w)
                else:
                    break
                r += 1
                self.list_win.addstr('\n\t')

            if str(i) == 'self' and k == 0:
                color = app.get_colpair('name')
            else:
                color = app.get_colpair('token')

            if k == in_arg or i == in_arg:
                color |= curses.A_BOLD

            if not py3:
                # See issue #138: We need to format tuple unpacking correctly
                # We use the undocumented function inspection.strseq() for
                # that. Fortunately, that madness is gone in Python 3.
                self.list_win.addstr(inspect.strseq(i, str), color)
            else:
                self.list_win.addstr(str(i), color)
            if kw is not None:
                self.list_win.addstr('=', punctuation_colpair)
                self.list_win.addstr(kw, app.get_colpair('token'))
            if k != len(args) -1:
                self.list_win.addstr(', ', punctuation_colpair)

        if _args:
            if args:
                self.list_win.addstr(', ', punctuation_colpair)
            self.list_win.addstr('*%s' % (_args, ),
                                 app.get_colpair('token'))

        if py3 and kwonly:
            if not _args:
                if args:
                    self.list_win.addstr(', ', punctuation_colpair)
                self.list_win.addstr('*', punctuation_colpair)
            marker = object()
            for arg in kwonly:
                self.list_win.addstr(', ', punctuation_colpair)
                color = app.get_colpair('token')
                if arg == in_arg:
                    color |= curses.A_BOLD
                self.list_win.addstr(arg, color)
                default = kwonly_defaults.get(arg, marker)
                if default is not marker:
                    self.list_win.addstr('=', punctuation_colpair)
                    self.list_win.addstr(repr(default),
                                         app.get_colpair('token'))

        if _kwargs:
            if args or _args or (py3 and kwonly):
                self.list_win.addstr(', ', punctuation_colpair)
            self.list_win.addstr('**%s' % (_kwargs, ),
                                 app.get_colpair('token'))
        self.list_win.addstr(')', punctuation_colpair)
        return r

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
        except SystemExit, e:
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
            if py3:
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
            if k < len(self.s_hist) -1:
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
            if py3:
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

        if not py3 and isinstance(t, unicode):
            t = t.encode(getpreferredencoding())

        self.stdout_history.append(t)

        self.echo(s)
        self.s_hist.append(s.rstrip())

    def show_list(self, items, topline=None, current_item=None):
        shared = Struct()
        shared.cols = 0
        shared.rows = 0
        shared.wl = 0
        y, x = self.scr.getyx()
        h, w = self.scr.getmaxyx()
        down = (y < h // 2)
        if down:
            max_h = h - y
        else:
            max_h = y + 1
        max_w = int(w * self.config.cli_suggestion_width)
        self.list_win.erase()
        if items:
            sep = '.'
            if os.path.sep in items[0]:
                # Filename completion
                sep = os.path.sep
            if sep in items[0]:
                items = [x.rstrip(sep).rsplit(sep)[-1] for x in items]
                if current_item:
                    current_item = current_item.rstrip(sep).rsplit(sep)[-1]

        if topline:
            height_offset = self.mkargspec(topline, down) + 1
        else:
            height_offset = 0

        def lsize():
            wl = max(len(i) for i in v_items) + 1
            if not wl:
                wl = 1
            cols = ((max_w - 2) // wl) or 1
            rows = len(v_items) // cols

            if cols * rows < len(v_items):
                rows += 1

            if rows + 2 >= max_h:
                rows = max_h - 2
                return False

            shared.rows = rows
            shared.cols = cols
            shared.wl = wl
            return True

        if items:
            # visible items (we'll append until we can't fit any more in)
            v_items = [items[0][:max_w - 3]]
            lsize()
        else:
            v_items = []

        for i in items[1:]:
            v_items.append(i[:max_w - 3])
            if not lsize():
                del v_items[-1]
                v_items[-1] = '...'
                break

        rows = shared.rows
        if rows + height_offset < max_h:
            rows += height_offset
            display_rows = rows
        else:
            display_rows = rows + height_offset

        cols = shared.cols
        wl = shared.wl

        if topline and not v_items:
            w = max_w
        elif wl + 3 > max_w:
            w = max_w
        else:
            t = (cols + 1) * wl + 3
            if t > max_w:
                t = max_w
            w = t

        if height_offset and display_rows + 5 >= max_h:
            del v_items[-(cols * height_offset):]

        if self.docstring is None:
            self.list_win.resize(rows + 2, w)
        else:
            docstring = self.format_docstring(self.docstring, max_w - 2,
                max_h - height_offset)
            docstring_string = ''.join(docstring)
            rows += len(docstring)
            self.list_win.resize(rows, max_w)

        if down:
            self.list_win.mvwin(y + 1, 0)
        else:
            self.list_win.mvwin(y - rows - 2, 0)

        if v_items:
            self.list_win.addstr('\n ')

        if not py3:
            encoding = getpreferredencoding()
        for ix, i in enumerate(v_items):
            padding = (wl - len(i)) * ' '
            if i == current_item:
                color = app.get_colpair('operator')
            else:
                color = app.get_colpair('main')
            if not py3:
                i = i.encode(encoding)
            self.list_win.addstr(i + padding, color)
            if ((cols == 1 or (ix and not (ix + 1) % cols))
                    and ix + 1 < len(v_items)):
                self.list_win.addstr('\n ')

        if self.docstring is not None:
            if not py3 and isinstance(docstring_string, unicode):
                docstring_string = docstring_string.encode(encoding, 'ignore')
            self.list_win.addstr('\n' + docstring_string,
                                 app.get_colpair('comment'))
            # XXX: After all the trouble I had with sizing the list box (I'm not very good
            # at that type of thing) I decided to do this bit of tidying up here just to
            # make sure there's no unnececessary blank lines, it makes things look nicer.

        y = self.list_win.getyx()[0]
        self.list_win.resize(y + 2, w)

        app.statusbar.scr.touchwin()
        app.statusbar.scr.noutrefresh()
        self.list_win.attron(app.get_colpair('main'))
        self.list_win.border()
        self.scr.touchwin()
        self.scr.cursyncup()
        self.scr.noutrefresh()

        # This looks a little odd, but I can't figure a better way to stick the cursor
        # back where it belongs (refreshing the window hides the list_win)

        self.scr.move(*self.scr.getyx())
        self.list_win.refresh()

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
        if self.is_beginning_of_the_line() and not back:
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

            current_word = self.current_string() or self.current_word()
            if not current_word:
                return True
        else:
            current_word = self.matches_iter.current_word

        # 3. check to see if we can expand the current word
        cseq = None
        if mode == autocomplete.SUBSTRING:
            if all([len(match.split(current_word)) == 2 for match in self.matches]):
                seq = [current_word + match.split(current_word)[1] for match in self.matches]
                cseq = os.path.commonprefix(seq)
        else:
            seq = self.matches
            cseq = os.path.commonprefix(seq)

        if cseq and mode != autocomplete.FUZZY:
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
                self.s = self.s[:-len(self.matches_iter.current())] + current_word

            current_match = back and self.matches_iter.previous() \
                                  or self.matches_iter.next()

            # update s with the new match
            if current_match:
                try:
                    self.show_list(self.matches, self.argspec, current_match)
                except curses.error:
                    # XXX: This is a massive hack, it will go away when I get
                    # cusswords into a good enough state that we can start
                    # using it.
                    self.list_win.border()
                    self.list_win.refresh()

                if self.config.autocomplete_mode == autocomplete.SIMPLE:
                    self.s += current_match[len(current_word):]
                else:
                    self.s = self.s[:-len(current_word)] + current_match

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

    def tokenize(self, s, newline=False):
        """Tokenize a line of code."""

        source = '\n'.join(self.buffer + [s])
        cursor = len(source) - self.cpos
        if self.cpos:
            cursor += 1
        stack = list()
        all_tokens = list(PythonLexer().get_tokens(source))
        # Unfortunately, Pygments adds a trailing newline and strings with
        # no size, so strip them
        while not all_tokens[-1][1]:
            all_tokens.pop()
        all_tokens[-1] = (all_tokens[-1][0], all_tokens[-1][1].rstrip('\n'))
        line = pos = 0
        parens = dict(zip('{([', '})]'))
        line_tokens = list()
        saved_tokens = list()
        search_for_paren = True
        for (token, value) in self._split_lines(all_tokens):
            pos += len(value)
            if token is Token.Text and value == '\n':
                line += 1
                # Remove trailing newline
                line_tokens = list()
                saved_tokens = list()
                continue
            line_tokens.append((token, value))
            saved_tokens.append((token, value))
            if not search_for_paren:
                continue
            under_cursor = (pos == cursor)
            if token is Token.Punctuation:
                if value in parens:
                    if under_cursor:
                        line_tokens[-1] = (Parenthesis.UnderCursor, value)
                        # Push marker on the stack
                        stack.append((Parenthesis, value))
                    else:
                        stack.append((line, len(line_tokens) - 1,
                                      line_tokens, value))
                elif value in parens.itervalues():
                    saved_stack = list(stack)
                    try:
                        while True:
                            opening = stack.pop()
                            if parens[opening[-1]] == value:
                                break
                    except IndexError:
                        # SyntaxError.. more closed parentheses than
                        # opened or a wrong closing paren
                        opening = None
                        if not saved_stack:
                            search_for_paren = False
                        else:
                            stack = saved_stack
                    if opening and opening[0] is Parenthesis:
                        # Marker found
                        line_tokens[-1] = (Parenthesis, value)
                        search_for_paren = False
                    elif opening and under_cursor and not newline:
                        if self.cpos:
                            line_tokens[-1] = (Parenthesis.UnderCursor, value)
                        else:
                            # The cursor is at the end of line and next to
                            # the paren, so it doesn't reverse the paren.
                            # Therefore, we insert the Parenthesis token
                            # here instead of the Parenthesis.UnderCursor
                            # token.
                            line_tokens[-1] = (Parenthesis, value)
                        (lineno, i, tokens, opening) = opening
                        if lineno == len(self.buffer):
                            self.highlighted_paren = (lineno, saved_tokens)
                            line_tokens[i] = (Parenthesis, opening)
                        else:
                            self.highlighted_paren = (lineno, list(tokens))
                            # We need to redraw a line
                            tokens[i] = (Parenthesis, opening)
                            self.reprint_line(lineno, tokens)
                        search_for_paren = False
                elif under_cursor:
                    search_for_paren = False
        if line != len(self.buffer):
            return list()
        return line_tokens

    def _split_lines(self, tokens):
        for (token, value) in tokens:
            if not value:
                continue
            while value:
                head, newline, value = value.partition('\n')
                yield (token, head)
                if newline:
                    yield (Token.Text, newline)


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
        self.c = color
        self.timer = 0
        self.settext(self._s, color)

    @property
    def _s(self):
        return " <C-r> Rewind  <C-s> Save  <F8> Pastebin <F9> Pager  <F2> Show Source "

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
            if not py3 and isinstance(s, unicode):
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
        app = self

        self.scr = scr
        self.config = config

        self.set_colors()
        main_win, status_win = self.init_wins()

        self.statusbar = Statusbar(status_win, self.config, color=app.get_colpair('main'))

        if locals_ is None:
            sys.modules['__main__'] = ModuleType('__main__')
            locals_ = sys.modules['__main__'].__dict__
        self.interpreter = repl.Interpreter(locals_, getpreferredencoding())

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

        if importcompletion.find_coroutine() or caller.paste_mode:
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
        #TODO: Document better what stuff is on the status bar.

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

        # FIXME: Gargh, bad design results in using globals without a refactor :(
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

        for i in range(63):
            if i > 7:
                j = i // 8
            else:
                j = c[self.config.color_scheme['background']]
            curses.init_pair(i + 1, i % 8, j)

        return c

    def getstdout(self):
        return self.clirepl.getstdout()

    def refresh(self):
        self.clirepl.scr.refresh()
        self.statusbar.refresh()

    def run(self, args, interactive, banner):
        if args:
            exit_value = 0
            try:
                bpython.config.args.exec_code(self.interpreter, args)
            except SystemExit, e:
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
        return (exit_value, app.getstdout())


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
    from bpython.cli import main
    sys.exit(main())

# vim: sw=4 ts=4 sts=4 ai et
