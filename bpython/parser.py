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

import itertools
import re

from bpython._py3compat import PythonLexer
from bpython.formatter import Parenthesis
from bpython import str_util
from pygments.token import Token

from six.moves import xrange


class ReplParser(object):
    def __init__(self, repl):
        self.repl = repl

    @property
    def buffer(self):
        return self.repl.buffer

    @property
    def cpos(self):
        return self.repl.cpos

    @property
    def s(self):
        return self.repl.s

    @property
    def highlighted_paren(self):
        return self.repl.highlighted_paren

    def reprint_line(self, *args):
        return self.repl.reprint_line(*args)

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
                elif value in parens.values():
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
                            self.repl.highlighted_paren = (lineno, saved_tokens)
                            line_tokens[i] = (Parenthesis, opening)
                        else:
                            self.repl.highlighted_paren = (lineno, list(tokens))
                            # We need to redraw a line
                            tokens[i] = (Parenthesis, opening)
                            self.reprint_line(lineno, tokens)
                        search_for_paren = False
                elif under_cursor:
                    search_for_paren = False
        if line != len(self.buffer):
            return list()
        return line_tokens


    def is_first_word(self):
        line = self.get_current_left_line()
        return str_util.is_only_word(line)

    def is_assignment_statement(self):
        return str_util.is_assignment_statement(self.s)

    def get_current_left_line(self):
        if self.cpos:
            line = self.s[:-self.cpos]
        else:
            line = self.s
        return line

    def get_current_word(self):
        line = self.get_current_left_line()
        return str_util.get_rclosure_word(line)

    def get_current_string(self):
        tokens = self.tokenize(self.s)
        string_tokens = list(itertools.takewhile(self._token_is_any_of([Token.String,
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

    def get_current_func(self):
        func, args = str_util.get_rfunc(self.s)
        if args:
            return func, len(args) - 1
        else:
            return func, 0

    def _split_lines(self, tokens):
        for (token, value) in tokens:
            if not value:
                continue
            while value:
                head, newline, value = value.partition('\n')
                yield (token, head)
                if newline:
                    yield (Token.Text, newline)

    def _token_is(self, token_type):
        """Return a callable object that returns whether a token is of the
        given type `token_type`."""

        def token_is_type(token):
            """Return whether a token is of a certain type or not."""
            token = token[0]
            while token is not token_type and token.parent:
                token = token.parent
            return token is token_type

        return token_is_type


    def _token_is_any_of(self, token_types):
        """Return a callable object that returns whether a token is any of the
        given types `token_types`."""
        is_token_types = map(self._token_is, token_types)

        def __token_is_any_of(token):
            return any(check(token) for check in is_token_types)

        return __token_is_any_of


