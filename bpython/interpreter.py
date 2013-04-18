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

import sys
import os
import code
import inspect
import traceback
import pydoc
import keyword

from pygments.token import Token
from bpython.completion import inspection
from bpython.completion.completers import import_completer
from bpython.util import getpreferredencoding
from bpython._py3compat import PythonLexer, PY3
from six import callable


class NothingType: pass

Nothing = NothingType()


def command_tokenize(line):
    result = ['']
    in_quote = False
    quote_type = None
    for c in line:
        if c == ' ':
            if not in_quote:
                if result[-1] == '':
                    pass
                else:
                    result.append('')
            else:
                result[-1] += c
        elif c in ['"', "'"]:
            if not in_quote:
                in_quote = True
                quote_type = c
                result[-1] += c
            else:
                if c == quote_type:
                    in_quote = False
                    quote_type = None
                    result[-1] += c
                else:
                    result[-1] += c
        elif c == "(":
            if not in_quote:
                in_quote = True
                quote_type = c
                result[-1] += c
            else:
                result[-1] += c
        elif c == ")":
            if not in_quote:
                in_quote = True
                quote_type = c
                result[-1] += c
            else:
                if quote_type == "(":
                    in_quote = False
                    quote_type = None
                    result[-1] += c
                else:
                    result[-1] += c
        else:
            result[-1] += c
    return result


class BPythonInterpreter(code.InteractiveInterpreter):
    def __init__(self, locals=None, encoding=None):
        """The syntaxerror callback can be set at any time and will be called
        on a caught syntax error. The purpose for this in bpython is so that
        the repl can be instantiated after the interpreter (which it
        necessarily must be with the current factoring) and then an exception
        callback can be added to the Interpeter instance afterwards - more
        specifically, this is so that autoindentation does not occur after a
        traceback."""

        self.command_table = {}
        self.encoding = encoding or sys.getdefaultencoding()
        self.syntaxerror_callback = None
        # Unfortunately code.InteractiveInterpreter is a classic class, so no super()
        code.InteractiveInterpreter.__init__(self, locals)

        self.locals['__command_table'] = self.command_table

    if not PY3:

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
                if not PY3:
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
            if not PY3:
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

    def register_command(self, name, function):
        if name not in self.command_table:
            self.command_table[name] = function
            return True
        else:
            return False

    def is_commandline(self, line):
        try:
            if not PY3 and isinstance(line, unicode):
                encoding = getpreferredencoding()
                words = map(lambda s: s.decode(encoding), command_tokenize(line.encode(encoding)))
            else:
                words = command_tokenize(line)
        except ValueError:
            return False
        else:
            if len(words) > 0:
                command_name = words[0]
                return command_name in self.command_table
            else:
                return False

    def get_command_spec(self, line):
        try:
            if not PY3 and isinstance(line, unicode):
                encoding = getpreferredencoding()
                words = map(lambda s: s.decode(encoding), command_tokenize(line.encode(encoding)))
            else:
                words = command_tokenize(line)
        except ValueError:
            pass
        else:
            if len(words) > 0:
                command_name = words[0]
                if command_name in self.command_table:
                    return [command_name, self.command_table[command_name]]

    def runcommand(self, line):
        try:
            if not PY3 and isinstance(line, unicode):
                encoding = getpreferredencoding()
                words = map(lambda s: s.decode(encoding), command_tokenize(line.encode(encoding)))
            else:
                words = command_tokenize(line)
        except ValueError:
            pass
        else:
            if len(words) > 0:
                command_name = words[0]
                if command_name in self.command_table:
                    source = "__command_table['%s'](%s)" % (command_name, ','.join(words[1:]))
                    self.runsource(source)

    def get_object(self, name):
        attributes = name.split('.')
        try:
            obj = eval(attributes.pop(0), self.locals)
        except Exception:
        # except (SyntaxError, NameError, AttributeError, IndexError, KeyError, TypeError):
            return Nothing
        else:
            while attributes:
                with inspection.AttrCleaner(obj):
                    try:
                        obj = getattr(obj, attributes.pop(0))
                    except AttributeError:
                        return Nothing
            return obj

    def get_argspec(self, line, func, arg_number, cw):
        if func:
            spec = self._get_argspec(func, arg_number)
        else:
            spec = None
        if not spec:
            if keyword.iskeyword(line):
                spec = inspection.KeySpec([line])
            elif self.is_commandline(line):
                spec = self.get_command_spec(line)
                spec = inspection.CommandSpec(spec)
            elif line.startswith('from ') or line.startswith('import '):
                obj = import_completer.get_object(cw, line)
                try:
                    spec = inspection.ImpSpec([cw, obj])
                except:
                    spec = None
            else:
                obj = self.get_object(line)
                if obj is not Nothing:
                    spec = inspection.ObjSpec([line, obj])
                else:
                    spec = None
        if spec is not None:
            try:
                f = spec[-1]
            except (IndexError, TypeError):
                spec.docstring = None
            else:
                if isinstance(spec, inspection.ImpSpec) and isinstance(f, str):
                    spec.docstring = None
                    try:
                        for token, value in PythonLexer().get_tokens(open(f).read()):
                            if token == Token.Literal.String.Doc:
                                spec.docstring = value.strip('"""').strip('r"""')
                            elif token == Token.Keyword and value == "def":
                                break
                            elif token == Token.Keyword and value == "class":
                                break
                            else:
                                pass
                    except:
                        spec.docstring = None
                    finally:
                        spec[-1] = None
                else:
                    try:
                        spec.docstring = pydoc.getdoc(f)
                    except IndexError:
                        spec.docstring = None
                    else:
                        # pydoc.getdoc() returns an empty string if no
                        # docstring was found
                        if not spec.docstring:
                            spec.docstring = None
        return spec

    def _get_argspec(self, func, arg_number):
        # Get the name of the current function and where we are in
        # the arguments

        f = self.get_object(func)
        if f is Nothing:
            return None

        if callable(f):
            if inspect.isclass(f):
                try:
                    if f.__init__ is not object.__init__:
                        f = f.__init__
                except AttributeError:
                    return None

            argspec = inspection.getargspec(func, f)
            if argspec:
                argspec.append(arg_number)
                argspec.append(f)
                argspec = inspection.ArgSpec(argspec)
                return argspec
            else:
                nospec = inspection.NoSpec([func, f])
                return nospec
        else:
            argspec = inspection.ObjSpec([func, f])
            return argspec

    def startup(self):
        startup = os.environ.get('PYTHONSTARTUP')
        default_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "default"))
        default_rc = os.path.join(default_dir, "rc.py")
        config_dir = os.path.expanduser('~/.bpython')
        rc = os.path.join(config_dir, 'rc.py')

        if PY3:
            self.runsource("import sys; sys.path.append('%s')" % default_dir, default_dir, 'exec')
        else:
            self.runsource("import sys; sys.path.append('%s')" % default_dir, default_dir, 'exec', encode=False)

        for filename in [startup, default_rc]:
            if filename and os.path.isfile(filename):
                with open(filename, 'r') as f:
                    if PY3:
                        self.runsource(f.read(), filename, 'exec')
                    else:
                        self.runsource(f.read(), filename, 'exec', encode=False)

        if PY3:
            self.runsource("sys.path.pop(); sys.path.append('%s'); del sys" % config_dir, config_dir, 'exec')
        else:
            self.runsource("sys.path.pop(); sys.path.append('%s'); del sys" % config_dir, config_dir, 'exec',
                           encode=False)

        for filename in [rc]:
            if filename and os.path.isfile(filename):
                with open(filename, 'r') as f:
                    if PY3:
                        self.runsource(f.read(), filename, 'exec')
                    else:
                        self.runsource(f.read(), filename, 'exec', encode=False)


