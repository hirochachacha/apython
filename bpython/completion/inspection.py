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
import inspect
import keyword
import pydoc
import re
import types

from pygments.token import Token

from bpython._py3compat import PythonLexer, PY3


if not PY3:
    _name = re.compile(r'[a-zA-Z_]\w*$')


class ObjSpec(list): pass


class ImpSpec(list): pass


class KeySpec(list): pass


class CommandSpec(list): pass


class ArgSpec(list): pass


class NoSpec(list): pass


class AttrCleaner(object):
    """A context manager that tries to make an object not exhibit side-effects
       on attribute lookup."""

    def __init__(self, obj):
        self.obj = obj

    def __enter__(self):
        """Try to make an object not exhibit side-effects on attribute
        lookup."""
        type_ = type(self.obj)
        __getattribute__ = None
        __getattr__ = None
        # Dark magic:
        # If __getattribute__ doesn't exist on the class and __getattr__ does
        # then __getattr__ will be called when doing
        #   getattr(type_, '__getattribute__', None)
        # so we need to first remove the __getattr__, then the
        # __getattribute__, then look up the attributes and then restore the
        # original methods. :-(
        # The upshot being that introspecting on an object to display its
        # attributes will avoid unwanted side-effects.
        if PY3 or type_ != types.InstanceType:
            __getattr__ = getattr(type_, '__getattr__', None)
            if __getattr__ is not None:
                try:
                    setattr(type_, '__getattr__', (lambda *_, **__: None))
                except TypeError:
                    __getattr__ = None
            __getattribute__ = getattr(type_, '__getattribute__', None)
            if __getattribute__ is not None:
                try:
                    setattr(type_, '__getattribute__', object.__getattribute__)
                except TypeError:
                    # XXX: This happens for e.g. built-in types
                    __getattribute__ = None
        self.attribs = (__getattribute__, __getattr__)
        # /Dark magic

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Restore an object's magic methods."""
        type_ = type(self.obj)
        __getattribute__, __getattr__ = self.attribs
        # Dark magic:
        if __getattribute__ is not None:
            setattr(type_, '__getattribute__', __getattribute__)
        if __getattr__ is not None:
            setattr(type_, '__getattr__', __getattr__)
            # /Dark magic


class _Repr(object):
    """
    Helper for `fixlongargs()`: Returns the given value in `__repr__()`.
    """

    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return self.value

    __str__ = __repr__


def parsekeywordpairs(signature):
    tokens = PythonLexer().get_tokens(signature)
    preamble = True
    stack = []
    substack = []
    parendepth = 0
    for token, value in tokens:
        if preamble:
            if token is Token.Punctuation and value == "(":
                preamble = False
            continue

        if token is Token.Punctuation:
            if value in ['(', '{', '[']:
                parendepth += 1
            elif value in [')', '}', ']']:
                parendepth -= 1
            elif value == ':' and parendepth == -1:
                # End of signature reached
                break
            if ((value == ',' and parendepth == 0) or
                    (value == ')' and parendepth == -1)):
                stack.append(substack)
                substack = []
                continue

        if value and (parendepth > 0 or value.strip()):
            substack.append(value)

    d = {}
    for item in stack:
        if len(item) >= 3:
            d[item[0]] = ''.join(item[2:])
    return d


def fixlongargs(f, argspec):
    """Functions taking default arguments that are references to other objects
    whose str() is too big will cause breakage, so we swap out the object
    itself with the name it was referenced with in the source by parsing the
    source itself !"""
    if argspec[3] is None:
        # No keyword args, no need to do anything
        return
    values = list(argspec[3])
    if not values:
        return
    keys = argspec[0][-len(values):]
    try:
        src = inspect.getsourcelines(f)
    except (IOError, IndexError):
        # IndexError is raised in inspect.findsource(), can happen in
        # some situations. See issue #94.
        return
    signature = ''.join(src[0])
    kwparsed = parsekeywordpairs(signature)

    for i, (key, value) in enumerate(zip(keys, values)):
        if len(repr(value)) != len(kwparsed[key]):
            values[i] = _Repr(kwparsed[key])

    argspec[3] = values


def getpydocspec(f, func):
    try:
        argspec = pydoc.getdoc(f)
    except NameError:
        return None

    rx = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*?)\((.*?)\)')
    s = rx.search(argspec)
    if s is None:
        return None

    if not hasattr(f, '__name__') or s.groups()[0] != f.__name__:
        return None

    args = list()
    defaults = list()
    varargs = varkwargs = None
    kwonly_args = list()
    kwonly_defaults = dict()
    for arg in s.group(2).split(','):
        arg = arg.strip()
        if arg.startswith('**'):
            varkwargs = arg[2:]
        elif arg.startswith('*'):
            varargs = arg[1:]
        else:
            arg, _, default = arg.partition('=')
            if varargs is not None:
                kwonly_args.append(arg)
                if default:
                    kwonly_defaults[arg] = default
            else:
                args.append(arg)
                if default:
                    defaults.append(default)

    return [func, (args, varargs, varkwargs, defaults,
                   kwonly_args, kwonly_defaults)]


def getargspec(func, f):
    # Check if it's a real bound method or if it's implicitly calling __init__
    # (i.e. FooClass(...) and not FooClass.__init__(...) -- the former would
    # not take 'self', the latter would:
    try:
        func_name = getattr(f, '__name__', None)
    except TypeError:
        return None

    try:
        is_bound_method = ((inspect.ismethod(f) and f.im_self is not None)
                           or (func_name == '__init__' and not
        func.endswith('.__init__')))
    except:
        # if f is a method from a xmlrpclib.Server instance, func_name ==
        # '__init__' throws xmlrpclib.Fault (see #202)
        return None
    try:
        if PY3:
            argspec = inspect.getfullargspec(f)
        else:
            argspec = inspect.getargspec(f)

        argspec = list(argspec)
        fixlongargs(f, argspec)
        argspec = [func, argspec, is_bound_method]
    except (TypeError, KeyError):
        with AttrCleaner(f):
            argspec = getpydocspec(f, func)
        if argspec is None:
            return None
        if inspect.ismethoddescriptor(f):
            argspec[1][0].insert(0, 'obj')
        argspec.append(is_bound_method)
    return argspec


def getmembers(object, predicate=None):
    """Return all members of an object as (name, value) pairs sorted by name.
    Optionally, only return members that satisfy a given predicate."""
    results = []
    for key in dir(object):
        try:
            value = getattr(object, key)
        except AttributeError:
            continue
        except:
            value = None
        if not predicate or predicate(value):
            results.append((key, value))
    results.sort()
    return results


def is_eval_safe_name(string):
    if PY3:
        return all(part.isidentifier() and not keyword.iskeyword(part)
                   for part in string.split('.'))
    else:
        return all(_name.match(part) and not keyword.iskeyword(part)
                   for part in string.split('.'))


