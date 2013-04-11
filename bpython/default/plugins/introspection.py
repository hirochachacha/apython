#!/usr/bin/env python
#coding: utf-8

import inspect
import pprint

import bpython
from bpython.pager import page as _page
from bpython._py3compat import PY3

from plugins.helpers import is_dictproxy


__all__ = ['page', 'show_source']


config = bpython.running.config


def page(data):
    if PY3:
        if not isinstance(data, str):
            if is_dictproxy(data):
                data = pprint.pformat(dict(data))
                data = "dictproxy(\n  " + '\n  '.join(data.split('\n')) + "\n)"
            else:
                data = pprint.pformat(data)
    else:
        if not isinstance(data, basestring):
            if is_dictproxy(data):
                data = pprint.pformat(dict(data))
                data = "dictproxy(\n  " + '\n  '.join(data.split('\n')) + "\n)"
            else:
                data = pprint.pformat(data)
    _page(data, use_hilight=config.highlight_show_source)


def show_source(obj):
    source = inspect.getsource(obj)
    page(source)
