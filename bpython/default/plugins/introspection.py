#!/usr/bin/env python
#coding: utf-8

from bpython.pager import page
from bpython.config import config
import inspect


def show_source(obj):
    source = inspect.getsource(obj)
    page(source, use_hilight=config.highlight_show_source)
