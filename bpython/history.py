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
import codecs


class History(object):
    def __init__(self, entries=None, allow_duplicates=True, ignore_blank=True):
        if entries is None:
            self.entries = []
        else:
            self.entries = list(entries)
        self.index = 0
        self.saved_line = ''
        self.allow_duplicates = allow_duplicates
        self.ignore_blank = ignore_blank

    def __getitem__(self, index):
        return self.entries[index]

    def __setitem__(self, index, value):
        self.entries[index] = value

    def __delitem__(self, index):
        del self.entries[index]

    def __iter__(self):
        for entry in self.entries:
            yield entry

    def __nonzero__(self):
        return bool(self.entries)

    def __bool__(self):
        return bool(self.entries)

    def __len__(self):
        return len(self.entries)

    def __contains__(self, item):
        return item in self.entries

    def __str__(self):
        return '\n'.join(self.entries) + '\n'

    @property
    def is_at_end(self):
        return self.index >= len(self.entries) or self.index == -1

    @property
    def is_at_start(self):
        return self.index == 0

    def append_raw(self, line):
        self.entries.append(line)

    def append(self, line):
        line = line.rstrip('\n')
        if line or not self.ignore_blank:
            if not self.allow_duplicates:
                # remove duplicates
                try:
                    while True:
                        self.entries.remove(line)
                except ValueError:
                    pass
            self.entries.append(line)

    def first(self):
        """Move back to the beginning of the history."""
        if not self.is_at_end:
            self.index = len(self.entries)
        return self.entries[-self.index]

    def back(self, start=True, search=False):
        """Move one step back in the history."""
        if not self.is_at_end:
            if search:
                self.index += self._find_partial_match_backward(self.saved_line)
            elif start:
                self.index += self._find_match_backward(self.saved_line)
            else:
                self.index += 1
        return self.entries[-self.index] if self.index else self.saved_line

    def forward(self, start=True, search=False):
        """Move one step forward in the history."""
        if self.index > 1:
            if search:
                self.index -= self._find_partial_match_forward(self.saved_line)
            elif start:
                self.index -= self._find_match_forward(self.saved_line)
            else:
                self.index -= 1
            return self.entries[-self.index] if self.index else self.saved_line
        else:
            self.index = 0
            return self.saved_line

    def last(self):
        """Move forward to the end of the history."""
        if not self.is_at_start:
            self.index = 0
        return self.entries[0]

    def enter(self, line):
        if self.index == 0:
            self.saved_line = line

    def load(self, filename, encoding):
        with codecs.open(filename, 'r', encoding, 'ignore') as hfile:
            for line in hfile:
                self.append(line)

    def reset(self):
        self.index = 0
        self.saved_line = ''

    def save(self, filename, encoding, lines=0):
        with codecs.open(filename, 'w', encoding, 'ignore') as hfile:
            for line in self.entries[-lines:]:
                hfile.write(line)
                hfile.write('\n')

    def _find_match_backward(self, search_term):
        filtered_list_len = len(self.entries) - self.index
        for idx, val in enumerate(reversed(self.entries[:filtered_list_len])):
            if val.startswith(search_term):
                return idx + 1
        return 0

    def _find_partial_match_backward(self, search_term):
        filtered_list_len = len(self.entries) - self.index
        for idx, val in enumerate(reversed(self.entries[:filtered_list_len])):
            if search_term in val:
                return idx + 1
        return 0

    def _find_match_forward(self, search_term):
        filtered_list_len = len(self.entries) - self.index + 1
        for idx, val in enumerate(self.entries[filtered_list_len:]):
            if val.startswith(search_term):
                return idx + 1
        return self.index

    def _find_partial_match_forward(self, search_term):
        filtered_list_len = len(self.entries) - self.index + 1
        for idx, val in enumerate(self.entries[filtered_list_len:]):
            if search_term in val:
                return idx + 1
        return self.index
