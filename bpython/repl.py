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
import code
import inspect
import os
import pydoc
import sys
import textwrap
import traceback
from glob import glob
from itertools import takewhile
from locale import getpreferredencoding

from pygments.token import Token

import bpython
from bpython.completion import importcompletion, inspection
from bpython._py3compat import PythonLexer, py3
from bpython.completion.autocomplete import Autocomplete
from bpython.history import History


if py3:
    basestring = str


class ObjSpec(list): pass


class KeySpec(list): pass


class ArgSpec(list): pass


class Interpreter(code.InteractiveInterpreter):
    def __init__(self, locals=None, encoding=None):
        """The syntaxerror callback can be set at any time and will be called
        on a caught syntax error. The purpose for this in bpython is so that
        the repl can be instantiated after the interpreter (which it
        necessarily must be with the current factoring) and then an exception
        callback can be added to the Interpeter instance afterwards - more
        specifically, this is so that autoindentation does not occur after a
        traceback."""

        self.encoding = encoding or sys.getdefaultencoding()
        self.syntaxerror_callback = None
        # Unfortunately code.InteractiveInterpreter is a classic class, so no super()
        code.InteractiveInterpreter.__init__(self, locals)

    if not py3:

        def runsource(self, source, filename='<input>', symbol='single',
                      encode=True):
            if encode:
                source = '# coding: %s\n%s' % (self.encoding,
                                               source.encode(self.encoding))
            return code.InteractiveInterpreter.runsource(self, source,
                                                         filename, symbol)

    def showsyntaxerror(self, filename=None):
        """Override the regular handler, the code's copied and pasted from
        code.py, as per showtraceback, but with the syntaxerror callback called
        and the text in a pretty colour."""
        if self.syntaxerror_callback is not None:
            self.syntaxerror_callback()

        type, value, sys.last_traceback = sys.exc_info()
        sys.last_type = type
        sys.last_value = value
        if filename and type is SyntaxError:
            # Work hard to stuff the correct filename in the exception
            try:
                msg, (dummy_filename, lineno, offset, line) = value.args
            except:
                # Not the format we expect; leave it alone
                pass
            else:
                # Stuff in the right filename and right lineno
                if not py3:
                    lineno -= 1
                value = SyntaxError(msg, (filename, lineno, offset, line))
                sys.last_value = value
        list = traceback.format_exception_only(type, value)
        self.writetb(list)

    def showtraceback(self):
        """This needs to override the default traceback thing
        so it can put it into a pretty colour and maybe other
        stuff, I don't know"""
        try:
            t, v, tb = sys.exc_info()
            sys.last_type = t
            sys.last_value = v
            sys.last_traceback = tb
            tblist = traceback.extract_tb(tb)
            del tblist[:1]
            # Set the right lineno (encoding header adds an extra line)
            if not py3:
                for i, (filename, lineno, module, something) in enumerate(tblist):
                    if filename == '<input>':
                        tblist[i] = (filename, lineno - 1, module, something)

            l = traceback.format_list(tblist)
            if l:
                l.insert(0, "Traceback (most recent call last):\n")
            l[len(l):] = traceback.format_exception_only(t, v)
        finally:
            tblist = tb = None

        self.writetb(l)

    def writetb(self, lines):
        """This outputs the traceback and should be overridden for anything
        fancy."""
        for line in lines:
            self.write(line)


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
        self.s_hist = []
        self.rl_history = History(allow_duplicates=self.config.hist_duplicates)
        self.stdin_history = History()
        self.stdout_history = History()
        self.evaluating = False
        self.completer = Autocomplete(self.interp.locals, config)
        self.matches = []
        self.matches_iter = MatchesIterator()
        self.argspec = None
        self.current_callable = None
        self.list_win_visible = False
        self._C = {}
        self.interact = Interaction(self.config)
        self.ps1 = '>>> '
        self.ps2 = '... '
        # Necessary to fix mercurial.ui.ui expecting sys.stderr to have this
        # attribute
        self.closed = False

        bpython.running = self

        pythonhist = os.path.expanduser(self.config.hist_file)
        if os.path.exists(pythonhist):
            self.rl_history.load(pythonhist,
                                 getpreferredencoding() or "ascii")


    #alias
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

    @property
    def current_word(self):
        raise (NotImplementedError("current_word should be implemented in subclass"))

    def reevaluate(self):
        raise (NotImplementedError("reevaluate should be implemented in subclass"))

    def tab(self):
        raise (NotImplementedError("tab should be implemented in subclass"))

    def tokenize(self, s, newline=False):
        raise (NotImplementedError("tokenize should be implemented in subclass"))

    def startup(self):
        """
        Execute PYTHONSTARTUP file if it exits. Call this after front
        end-specific initialisation.
        """
        startup = os.environ.get('PYTHONSTARTUP')
        default_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "default"))
        default_rc = os.path.join(default_dir, "rc.py")
        config_dir = os.path.expanduser('~/.bpython')
        rc = os.path.join(config_dir, 'rc.py')

        if py3:
            self.interp.runsource("import sys; sys.path.append('%s')" % default_dir, default_dir, 'exec')
            self.interp.runsource("sys.path.append('%s'); del sys" % config_dir, config_dir, 'exec')
        else:
            self.interp.runsource("import sys; sys.path.append('%s')" % default_dir, default_dir, 'exec', encode=False)
            self.interp.runsource("sys.path.append('%s'); del sys" % config_dir, config_dir, 'exec', encode=False)

        for filename in [startup, default_rc, rc]:
            if filename and os.path.isfile(filename):
                with open(filename, 'r') as f:
                    if py3:
                        self.interp.runsource(f.read(), filename, 'exec')
                    else:
                        self.interp.runsource(f.read(), filename, 'exec', encode=False)

    @property
    def stdout(self):
        return str(self.stdout_history)

    @property
    def current_string(self):
        """If the line ends in a string get it, otherwise return ''"""
        tokens = self.tokenize(self.current_line)
        string_tokens = list(takewhile(token_is_any_of([Token.String,
                                                        Token.Text]),
                                       reversed(tokens)))
        if not string_tokens:
            return ''
        opening = string_tokens.pop()[1]
        string = list()
        for (token, value) in reversed(string_tokens):
            if token is Token.Text:
                continue
            elif opening is None:
                opening = value
            elif token is Token.String.Doc:
                string.append(value[3:-3])
                opening = None
            elif value == opening:
                opening = None
                string = list()
            else:
                string.append(value)

        if opening is None:
            return ''
        return ''.join(string)

    def get_object(self, name):
        attributes = name.split('.')
        obj = eval(attributes.pop(0), self.interp.locals)
        while attributes:
            with inspection.AttrCleaner(obj):
                obj = getattr(obj, attributes.pop(0))
        return obj

    def get_args(self, line):
        """Check if an unclosed parenthesis exists, then attempt to get the
        argspec() for it. On success, update self.argspec and return True,
        otherwise set self.argspec to None and return False"""

        self.current_callable = None

        if not self.config.arg_spec:
            return False

        # Get the name of the current function and where we are in
        # the arguments
        stack = [['', 0, '']]
        try:
            for (token, value) in PythonLexer().get_tokens(line):
                if token is Token.Punctuation:
                    if value in '([{':
                        stack.append(['', 0, value])
                    elif value in ')]}':
                        stack.pop()
                    elif value == ',':
                        try:
                            stack[-1][1] += 1
                        except TypeError:
                            stack[-1][1] = ''
                        stack[-1][0] = ''
                    elif value == ':' and stack[-1][2] == 'lambda':
                        stack.pop()
                    else:
                        stack[-1][0] = ''
                elif (token is Token.Name or token in Token.Name.subtypes or
                                  token is Token.Operator and value == '.'):
                    stack[-1][0] += value
                elif token is Token.Operator and value == '=':
                    stack[-1][1] = stack[-1][0]
                    stack[-1][0] = ''
                elif token is Token.Keyword and value == 'lambda':
                    stack.append(['', 0, value])
                else:
                    stack[-1][0] = ''
            while stack[-1][2] in '[{':
                stack.pop()
            _, arg_number, _ = stack.pop()
            func, _, _ = stack.pop()
        except IndexError:
            return False
        if not func:
            return False

        try:
            f = self.get_object(func)
        except (AttributeError, NameError, SyntaxError):
            return False

        if inspection.is_callable(f):
            if inspect.isclass(f):
                try:
                    if f.__init__ is not object.__init__:
                        f = f.__init__
                except AttributeError:
                    return None
            self.current_callable = f

            self.argspec = inspection.getargspec(func, f)
            if self.argspec:
                self.argspec.append(arg_number)
                self.argspec = ArgSpec(self.argspec)
                return True
            return False
        else:
            raise
            objspec = [func, f]
            self.argspec = ObjSpec(objspec)
            return True

    @property
    def current_object(self):
        """Return the object which is bound to the
        current name in the current input line. Return `None` if the
        source cannot be found."""
        obj = None
        try:
            line = self.current_line
            if inspection.is_eval_safe_name(line):
                obj = self.get_object(line)
        except (AttributeError, IOError, NameError, TypeError):
            obj = None

        return obj

    def complete(self, tab=False):
        """Construct a full list of possible completions and construct and
        display them in a window. Also check if there's an available argspec
        (via the inspect module) and bang that on top of the completions too.
        The return value is whether the list_win is visible or not."""
        self.docstring = None
        if not self.get_args(self.current_line):
            self.argspec = None
        elif self.current_callable is not None:
            try:
                self.docstring = pydoc.getdoc(self.current_callable)
            except IndexError:
                self.docstring = None
            else:
                # pydoc.getdoc() returns an empty string if no
                # docstring was found
                if not self.docstring:
                    self.docstring = None

        current_word = self.current_word
        current_string = self.current_string

        if not current_word:
            self.matches = []
            self.matches_iter.update()
        if not (current_word or current_string):
            return bool(self.argspec)

        if current_string and tab:
            # Filename completion
            self.matches = []
            username = current_string.split(os.path.sep, 1)[0]
            user_dir = os.path.expanduser(username)
            for filename in glob(os.path.expanduser(current_string + '*')):
                if os.path.isdir(filename):
                    filename += os.path.sep
                if current_string.startswith('~'):
                    filename = username + filename[len(user_dir):]
                self.matches.append(filename)
            self.matches_iter.update(current_string, self.matches)
            return bool(self.matches)
        elif current_string:
            # Do not provide suggestions inside strings, as one cannot tab
            # them so they would be really confusing.
            self.matches_iter.update()
            return False

        # Check for import completion
        e = False
        matches = importcompletion.complete(self.current_line, current_word)
        if matches is not None and not matches:
            self.matches = []
            self.matches_iter.update()
            return False

        if matches is None:
            # Nope, no import, continue with normal completion
            try:
                self.completer.complete(current_word, 0)
            except Exception:
                # This sucks, but it's either that or list all the exceptions that could
                # possibly be raised here, so if anyone wants to do that, feel free to send me
                # a patch. XXX: Make sure you raise here if you're debugging the completion
                # stuff !
                e = True
            else:
                matches = self.completer.matches
                if (self.config.complete_magic_methods and self.buffer and
                        self.buffer[0].startswith("class ") and
                        self.current_line.lstrip().startswith("def ")):
                    matches.extend(name for name in self.config.magic_methods
                                   if name.startswith(current_word))

        if not e and self.argspec:
            matches.extend(name + '=' for name in self.argspec[1][0]
                           if isinstance(name, basestring) and name.startswith(current_word))
            if py3:
                matches.extend(name + '=' for name in self.argspec[1][4]
                               if name.startswith(current_word))

        # unless the first character is a _ filter out all attributes starting with a _
        if not e and not current_word.split('.')[-1].startswith('_'):
            matches = [match for match in matches
                       if not match.split('.')[-1].startswith('_')]

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
                except EnvironmentError, err:
                    self.interact.notify("Error occured while writing to file %s (%s) " % (histfilename, err.strerror))
                    self.rl_history.entries = oldhistory
                    self.rl_history.append(s)
            else:
                self.rl_history.append(s)

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


def next_token_inside_string(s, inside_string):
    """Given a code string s and an initial state inside_string, return
    whether the next token will be inside a string or not."""
    for token, value in PythonLexer().get_tokens(s):
        if token is Token.String:
            value = value.lstrip('bBrRuU')
            if value in ['"""', "'''", '"', "'"]:
                if not inside_string:
                    inside_string = value
                elif value == inside_string:
                    inside_string = False
    return inside_string


def token_is(token_type):
    """Return a callable object that returns whether a token is of the
    given type `token_type`."""

    def token_is_type(token):
        """Return whether a token is of a certain type or not."""
        token = token[0]
        while token is not token_type and token.parent:
            token = token.parent
        return token is token_type

    return token_is_type


def token_is_any_of(token_types):
    """Return a callable object that returns whether a token is any of the
    given types `token_types`."""
    is_token_types = map(token_is, token_types)

    def token_is_any_of(token):
        return any(check(token) for check in is_token_types)

    return token_is_any_of


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
