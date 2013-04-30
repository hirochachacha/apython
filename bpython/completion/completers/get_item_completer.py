#!/usr/bin/env python
#coding: utf-8


import collections
import re

from six import PY3
from bpython.util import isolate, debug, getpreferredencoding


@isolate
def complete(expr, attr, locals_):
    if not expr:
        return []
    try:
        obj = eval(expr, locals_)
    except Exception:
        return []
    else:
        try:
            pattern = re.compile(r'.*%s.*' % '.*'.join(list(attr)))
            if isinstance(obj, collections.Mapping):
                words = sorted(key_wrap(word) for word in obj.keys())
                return [word for word in words if pattern.search(word)]
            elif isinstance(obj, collections.Sequence):
                words = (str(word) + ']' for word in range(len(obj)))
                return [word for word in words if pattern.search(word)]
            else:
                return []
        except (re.error, TypeError):
            return []


def key_wrap(obj):
    if PY3:
        if isinstance(obj, str):
            return '"' + obj + '"]'
        elif isinstance(obj, bytes):
            return 'b"' + obj.decode(getpreferredencoding()) + '"]'
        else:
            return obj
    else:
        if isinstance(obj, str):
            return '"' + obj + '"]'
        elif isinstance(obj, unicode):
            return 'u"' + str(obj) + '"]'
        else:
            return obj
