#!/usr/bin/env python
#coding: utf-8

# The MIT License
#
# Copyright (c) 2009-2012 the bpython authors.
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

import rlcompleter
import re
import keyword
import inspect
from bpython.completion import inspection
from bpython._py3compat import PY3
from six.moves import builtins
from six import callable


# Needed for special handling of __abstractmethods__
# abc only exists since 2.6, so check both that it exists and that it's
# the one we're expecting
try:
    import abc

    abc.ABCMeta
    has_abc = True
except (ImportError, AttributeError):
    has_abc = False

# Autocomplete modes
SIMPLE = 'simple'
SUBSTRING = 'substring'
FUZZY = 'fuzzy'

WITHOUT_CALLABLE_POSTFIX = set(['basestring'])


class Completer(rlcompleter.Completer):
    def __init__(self, locals_=None, config=None):
        rlcompleter.Completer.__init__(self, locals_)
        self.locals = locals_
        if hasattr(config, 'autocomplete_mode'):
            if config.autocomplete_mode in ['simple', 'fuzzy', 'substring']:
                self.autocomplete_mode = config.autocomplete_mode
            else:
                raise
        else:
            self.autocomplete_mode = SUBSTRING

    def global_matches(self, text):
        """Compute matches when text is a simple name.
        Return a list of all keywords, built-in functions and names currently
        defined in self.locals that match.
        """

        words = set()
        n = len(text)
        for word in keyword.kwlist:
            if self._method_match(word, n, text):
                words.add(word)
        for nspace in [builtins.__dict__, self.locals]:
            for word, val in nspace.items():
                if self._method_match(word, len(text), text) and word != "__builtins__":
                    words.add(self._callable_postfix(val, word))
        matches = sorted(words)
        return matches

    def attr_matches(self, text):
        """Taken from rlcompleter.py and bent to my will.
        """

        # Gna, Py 2.6's rlcompleter searches for __call__ inside the
        # instance instead of the type, so we monkeypatch to prevent
        # side-effects (__getattr__/__getattribute__)
        m = re.match(r"(\w+(\.\w+)*)\.(\w*)", text)
        if not m:
            return []

        expr, attr = m.group(1, 3)
        if expr.isdigit():
            # Special case: float literal, using attrs here will result in
            # a SyntaxError
            return []
        try:
            obj = eval(expr, self.locals)
        except (NameError, SyntaxError):
            return []
        else:
            with inspection.AttrCleaner(obj):
                matches = self._attr_lookup(obj, expr, attr)
            return matches

    def _attr_lookup(self, obj, expr, attr):
        """Second half of original attr_matches method factored out so it can
        be wrapped in a safe try/finally block in case anything bad happens to
        restore the original __getattribute__ method."""

        words = []
        for k, v in inspect.getmembers(obj):
            words.append(self._callable_postfix(v, k))

        if hasattr(obj, '__class__'):
            for k, v in inspect.getmembers(obj.__class__):
                words.append(self._callable_postfix(v, k))

        if hasattr(obj, '__class__') and has_abc and not isinstance(obj.__class__, abc.ABCMeta):
            try:
                words.remove('__abstractmethods__')
            except ValueError:
                pass

        matches = []
        n = len(attr)
        for word in words:
            if self._method_match(word, n, attr) and word != "__builtins__":
                matches.append("%s.%s" % (expr, word))
        return sorted(matches)

    def _callable_postfix(self, value, word):
        """rlcompleter's _callable_postfix done right."""
        with inspection.AttrCleaner(value):
            if callable(value):
                if not PY3:
                    if word not in WITHOUT_CALLABLE_POSTFIX:
                        word += '('
                else:
                    word += '('
        return word

    def _method_match(self, word, size, text):
        if self.autocomplete_mode == SIMPLE:
            return word[:size] == text
        elif self.autocomplete_mode == SUBSTRING:
            s = r'.*%s.*' % text
            return re.search(s, word)
        elif self.autocomplete_mode == FUZZY:
            s = r'.*%s.*' % '.*'.join(list(text))
            return re.search(s, word)
        else:
            raise

