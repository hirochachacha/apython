#!/usr/bin/env python
#coding: utf-8

# The MIT License
#
# Copyright (c) 2009-2011 the bpython authors.
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

from __future__ import with_statement
import os
import sys
import re
import textwrap
from itertools import takewhile

from pygments.token import Token

from bpython.completion import inspection
from bpython.completion.completer import BPythonCompleter
from bpython.parser import ReplParser
from bpython.history import History

from bpython.util import getpreferredencoding, debug
from bpython._py3compat import PythonLexer, PY3


if PY3:
    basestring = str


class MatchesIterator(object):
    def __init__(self, current_word='', matches=None):
        self.current_word = current_word
        if matches:
            self.matches = list(matches)
        else:
            self.matches = []
        self.index = -1
        self.is_wait = False

    def __nonzero__(self):
        return self.index != -1

    def __bool__(self):
        return self.index != -1

    def __iter__(self):
        return self

    def current(self):
        if self.index == -1:
            raise ValueError('No current match.')
        return self.matches[self.index]

    def wait(self):
        self.is_wait = True

    def next(self):
        if self.is_wait:
            self.is_wait = False
        else:
            self.index = (self.index + 1) % len(self.matches)
        return self.matches[self.index]

    def previous(self):
        self.is_wait = False
        if self.index <= 0:
            self.index = len(self.matches)
        self.index -= 1

        return self.matches[self.index]

    def update(self, current_word='', matches=None):
        if not matches: matches = []
        if current_word != self.current_word:
            self.current_word = current_word
            self.matches = list(matches)
            self.index = -1

    def force_update(self, matches):
        self.matches = list(matches)
        self.current_word = ''
        self.index = -1


class Interaction(object):
    def __init__(self, config, statusbar=None):
        self.config = config

        if statusbar:
            self.statusbar = statusbar

    def confirm(self, s):
        raise NotImplementedError

    def notify(self, s, n=10):
        raise NotImplementedError

    def file_prompt(self, s):
        raise NotImplementedError


class Repl(object):
    """Implements the necessary guff for a Python-repl-alike interface

    The execution of the code entered and all that stuff was taken from the
    Python code module, I had to copy it instead of inheriting it, I can't
    remember why. The rest of the stuff is basically what makes it fancy.

    It reads what you type, passes it to a lexer and highlighter which
    returns a formatted string. This then gets passed to echo() which
    parses that string and prints to the curses screen in appropriate
    colours and/or bold attribute.

    The Repl class also keeps two stacks of lines that the user has typed in:
    One to be used for the undo feature. I am not happy with the way this
    works.  The only way I have been able to think of is to keep the code
    that's been typed in in memory and re-evaluate it in its entirety for each
    "undo" operation. Obviously this means some operations could be extremely
    slow.  I'm not even by any means certain that this truly represents a
    genuine "undo" implementation, but it does seem to be generally pretty
    effective.

    If anyone has any suggestions for how this could be improved, I'd be happy
    to hear them and implement it/accept a patch. I researched a bit into the
    idea of keeping the entire Python state in memory, but this really seems
    very difficult (I believe it may actually be impossible to work) and has
    its own problems too.

    The other stack is for keeping a history for pressing the up/down keys
    to go back and forth between lines.

    XXX Subclasses should implement echo, current_line, current_word
    """

    def __init__(self, interp, config):
        """Initialise the repl.

        interp is a Python code.InteractiveInterpreter instance

        config is a populated bpython.config.Struct.
        """
        self.config = config
        self.buffer = []
        self.interp = interp
        self.interp.syntaxerror_callback = self.clear_current_line
        self.match = False
        self.s = ""
        self.cpos = 0
        self.s_hist = []
        self.rl_history = History(allow_duplicates=self.config.hist_duplicates)
        self.stdin_history = History()
        self.stdout_history = History()
        self.evaluating = False
        self.completer = BPythonCompleter(self.interp.locals, config)
        self.parser = ReplParser(self)
        self.matches = []
        self.matches_iter = MatchesIterator()
        self.argspec = None
        self.list_win_visible = False
        self._C = {}
        self.interact = Interaction(self.config)
        self.ps1 = '>>> '
        self.ps2 = '... '

        # Necessary to fix mercurial.ui.ui expecting sys.stderr to have this
        # attribute
        self.closed = False

        pythonhist = os.path.expanduser(self.config.hist_file)
        if os.path.exists(pythonhist):
            self.rl_history.load(pythonhist,
                                 getpreferredencoding() or "ascii")


    def register_command(self, name, function=None, without_completion=False):
        def inner(function, name=name):
            if not name:
                name = function.__name__.replace('_', '-')
            if self.interp.register_command(name, function) and not without_completion:
                name += " "
                self.completer.register_command(name)

        if not function:
            return inner
        else:
            return inner(function, name)

    @property
    def history(self):
        return self.stdin_history

    @property
    def current_line(self):
        raise (NotImplementedError("current_line should be implemented in subclass"))

    def clear_current_line(self):
        """This is used as the exception callback for the Interpreter instance.
        It prevents autoindentation from occuring after a traceback."""
        raise (NotImplementedError("clear_current_line should be implemented in subclass"))

    def reevaluate(self):
        raise (NotImplementedError("reevaluate should be implemented in subclass"))

    def tab(self):
        raise (NotImplementedError("tab should be implemented in subclass"))

    def tokenize(self, s, newline=False):
        """Tokenize a line of code."""
        return self.parser.tokenize(s, newline)

    def startup(self):
        """
        Execute PYTHONSTARTUP file if it exits. Call this after front
        end-specific initialisation.
        """
        self.interp.startup()

    @property
    def stdout(self):
        return str(self.stdout_history)

    @property
    def current_string(self):
        """If the line ends in a string get it, otherwise return ''"""
        return self.parser.get_current_string()

    @property
    def current_word(self):
        """Return the current word, i.e. the (incomplete) word directly to the
        left of the cursor"""
        return self.parser.get_current_word()

    @property
    def is_first_word(self):
        return self.parser.is_first_word()

    @property
    def is_only_word(self):
        return self.parser.is_only_word()

    @property
    def is_assignment_statement(self):
        return self.parser.is_assignment_statement()

    def get_object(self, name):
        return self.interp.get_object(name)

    def set_argspec(self):
        """Check if an unclosed parenthesis exists, then attempt to get the
        argspec() for it. On success, update self.argspec and return True,
        otherwise set self.argspec to None and return False"""

        if not self.config.arg_spec:
            self.argspec = None
        else:
            func, arg_number = self.parser.get_current_func()
            self.argspec = self.interp.get_argspec(self, func, arg_number)

    @property
    def current_object(self):
        """Return the object which is bound to the
        current name in the current input line. Return `None` if the
        source cannot be found."""
        obj = None
        line = self.current_line
        if inspection.is_eval_safe_name(line):
            obj = self.get_object(line)

        return obj

    def complete(self, tab=False):
        """Construct a full list of possible completions and construct and
        display them in a window. Also check if there's an available argspec
        (via the inspect module) and bang that on top of the completions too.
        The return value is whether the list_win is visible or not."""
        self.set_argspec()

        current_word = self.current_word
        current_string = self.current_string
        line = self.current_line.lstrip()
        # from bpython import str_util
        # sb_name, sb_val = str_util.get_rsbracket(self.s)
        # if sb_name:
            # sb_obj = self.get_object(sb_name)
            # completer = self.completer
            # attr = sb_val
            # n = len(attr)
            # try:
                # if hasattr(sb_obj, 'keys'):
                    # words = getattr(sb_obj, 'keys')()
                    # self.matches = sorted(word for word in words if completer._method_match(word, n, attr))
                # else:
                    # words = list(range(len(sb_obj)))
                    # self.matches = sorted(word for word in words if completer._method_match(word, n, attr))
            # except (TypeError, AttributeError):
                # self.matches = []
            # self.matches_iter.force_update(self.matches)
            # return bool(self.matches)
        if not current_word:
            self.matches = []
            self.matches_iter.update()
            return bool(self.argspec)
        elif not (current_word or current_string):
            return bool(self.argspec)
        elif current_string:
            if tab:
                # Filename completion
                self.completer.file_complete(current_string)
                self.matches = self.completer.matches
                self.matches_iter.update(current_string, self.matches)
                return bool(self.matches)
            else:
                # Do not provide suggestions inside strings, as one cannot tab
                # them so they would be really confusing.
                self.matches = []
                self.matches_iter.update()
                return False
        elif (self.config.complete_magic_methods
                and self.buffer
                and self.buffer[0].startswith("class ")
                and line.startswith('def ')):
            self.matches = [name for name in self.config.magic_methods
                            if name.startswith(current_word)]
            self.matches_iter.update(current_word, self.matches)
            return bool(self.matches)
        elif line.startswith('class ') or line.startswith('def '):
            self.matches = []
            self.matches_iter.update()
            return False
        elif line.startswith('from ') or line.startswith('import '):
            self.completer.import_complete(current_word, self.current_line)
            self.matches = self.completer.matches
            self.matches_iter.update(current_word, self.matches)
            return bool(self.matches)

        e = False
        try:
            if len(self.buffer) == 0 and self.is_first_word:
                self.completer.complete(current_word, with_command=True)
            else:
                self.completer.complete(current_word)
        except (AttributeError, re.error):
            e = True
        except Exception:
            err = sys.exc_info()[1]
            raise err
            # This sucks, but it's either that or list all the exceptions that could
            # possibly be raised here, so if anyone wants to do that, feel free to send me
            # a patch. XXX: Make sure you raise here if you're debugging the completion
            # stuff !
            e = True
        else:
            matches = self.completer.matches

        if not e and self.argspec and isinstance(self.argspec, inspection.ArgSpec):
            matches.extend(name + '=' for name in self.argspec[1][0]
                           if isinstance(name, basestring) and name.startswith(current_word))
            if PY3:
                matches.extend(name + '=' for name in self.argspec[1][4]
                               if name.startswith(current_word))

        if e or not matches:
            self.matches = []
            self.matches_iter.update()
            if not self.argspec:
                return False
        else:
            # remove duplicates
            self.matches = sorted(set(matches))

        if len(self.matches) == 1 and not self.config.auto_display_list:
            self.list_win_visible = True
            self.tab()
            return False

        self.matches_iter.update(current_word, self.matches)
        return True

    def format_docstring(self, docstring, width, height):
        """Take a string and try to format it into a sane list of strings to be
        put into the suggestion box."""
        lines = docstring.split('\n')
        out = []
        i = 0
        for line in lines:
            i += 1
            if not line.strip():
                out.append('\n')
            for block in textwrap.wrap(line, width):
                out.append('  ' + block + '\n')
                if i >= height:
                    return out
                i += 1
                # Drop the last newline
        out[-1] = out[-1].rstrip()
        return out

    def next_indentation(self):
        """Return the indentation of the next line based on the current
        input buffer."""
        if self.buffer:
            indentation = next_indentation(self.buffer[-1],
                                           self.config.tab_length)
            if indentation and self.config.dedent_after > 0:
                line_is_empty = lambda line: not line.strip()
                empty_lines = takewhile(line_is_empty, reversed(self.buffer))
                if sum(1 for _ in empty_lines) >= self.config.dedent_after:
                    indentation -= 1
        else:
            indentation = 0
        return indentation

    def formatforfile(self, s):
        """Format the stdout buffer to something suitable for writing to disk,
        i.e. without >>> and ... at input lines and with "# OUT: " prepended to
        output lines."""

        def process():
            for line in s.split('\n'):
                if line.startswith(self.ps1):
                    yield line[len(self.ps1):]
                elif line.startswith(self.ps2):
                    yield line[len(self.ps2):]
                elif line.rstrip():
                    yield "# OUT: %s" % (line,)

        return "\n".join(process())

    def write2file(self):
        """Prompt for a filename and write the current contents of the stdout
        buffer to disk."""

        try:
            fn = self.interact.file_prompt('Save to file (Esc to cancel): ')
            if not fn:
                self.interact.notify("Save cancelled.")
                return
        except ValueError:
            self.interact.notify("Save cancelled.")
            return

        if fn.startswith('~'):
            fn = os.path.expanduser(fn)
        if not fn.endswith('.py') and self.config.save_append_py:
            fn += '.py'

        mode = 'w'
        if os.path.exists(fn):
            mode = self.interact.file_prompt('%s already exists. Do you want '
                                             'to (c)ancel, (o)verwrite or '
                                             '(a)ppend? ' % (fn, ))
            if mode in ('o', 'overwrite'):
                mode = 'w'
            elif mode in ('a', 'append'):
                mode = 'a'
            else:
                self.interact.notify('Save cancelled.')
                return

        s = self.formatforfile(self.stdout)

        try:
            f = open(fn, mode)
            f.write(s)
            f.close()
        except IOError:
            self.interact.notify("Disk write error for file '%s'." % (fn, ))
        else:
            self.interact.notify('Saved to %s.' % (fn, ))

    def push(self, s, insert_into_history=True):
        """Push a line of code onto the buffer so it can process it all
        at once when a code block ends"""
        s = s.rstrip('\n')
        self.buffer.append(s)

        if insert_into_history:
            if self.config.hist_length:
                histfilename = os.path.expanduser(self.config.hist_file)
                oldhistory = self.rl_history.entries
                self.rl_history.entries = []
                if os.path.exists(histfilename):
                    self.rl_history.load(histfilename, getpreferredencoding())
                self.rl_history.append(s)
                try:
                    self.rl_history.save(histfilename, getpreferredencoding(), self.config.hist_length)
                except EnvironmentError:
                    e = sys.exc_info()[1]
                    self.interact.notify("Error occured while writing to file %s (%s) " % (histfilename, e.strerror))
                    self.rl_history.entries = oldhistory
                    self.rl_history.append(s)
            else:
                self.rl_history.append(s)

        if len(self.buffer) == 1:
            line = self.buffer[0]
            if self.interp.is_commandline(line) and not self.is_assignment_statement:
                result = self.interp.runcommand(line)
                self.buffer = []
                return result

        more = self.interp.runsource('\n'.join(self.buffer))

        if not more:
            self.buffer = []

        return more

    def undo(self, n=1):
        """Go back in the undo history n steps and call reeavluate()
        Note that in the program this is called "Rewind" because I
        want it to be clear that this is by no means a true undo
        implementation, it is merely a convenience bonus."""
        if not self.history:
            return None

        if len(self.history) < n:
            n = len(self.history)

        entries = list(self.rl_history.entries)

        self.history.entries = self.history[:-n]

        self.reevaluate()

        self.rl_history.entries = entries

    def flush(self):
        """Olivier Grisel brought it to my attention that the logging
        module tries to call this method, since it makes assumptions
        about stdout that may not necessarily be true. The docs for
        sys.stdout say:

        "stdout and stderr needn't be built-in file objects: any
         object is acceptable as long as it has a write() method
         that takes a string argument."

        So I consider this to be a bug in logging, and this is a hack
        to fix it, unfortunately. I'm sure it's not the only module
        to do it."""

    def close(self):
        """See the flush() method docstring."""


def next_indentation(line, tab_length):
    """Given a code line, return the indentation of the next line."""
    line = line.expandtabs(tab_length)
    indentation = (len(line) - len(line.lstrip(' '))) // tab_length
    if line.rstrip().endswith(':'):
        indentation += 1
    elif indentation >= 1:
        if line.lstrip().startswith(('return', 'pass', 'raise', 'yield')):
            indentation -= 1
    return indentation


def extract_exit_value(args):
    """Given the arguments passed to `SystemExit`, return the value that
    should be passed to `sys.exit`.
    """
    if len(args) == 0:
        return None
    elif len(args) == 1:
        return args[0]
    else:
        return args
