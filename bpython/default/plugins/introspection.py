#!/usr/bin/env python
#coding: utf-8

import inspect
import pprint

from bpython.pager import page as _page
from bpython.config import config
from bpython._py3compat import PY3


def page(data):
    if PY3:
        if not isinstance(data, str):
            data = pprint.pformat(data)
    else:
        if not isinstance(data, basestring):
            data = pprint.pformat(data)
    _page(data, use_hilight=config.highlight_show_source)


def show_source(obj):
    source = inspect.getsource(obj)
    page(source)
