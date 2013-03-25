#!/usr/bin/env python
#coding: utf-8

from plugins.editing import edit_object
from plugins.introspection import (show_source, page)

import bpython
from bpython.key.dispatch_table import dispatch_table


@dispatch_table.set_handler_on('F2')
def do_show_source(dispatcher):
    from bpython.translations import _
    obj = dispatcher.repl.get_current_object()
    if obj is not None:
        show_source(obj)
    else:
        dispatcher.repl.statusbar.message(_('Cannot show source.'))
    return ''


@dispatch_table.set_handler_on('F9')
def do_pager(dispatcher):
    page(dispatcher.repl.getstdout())
    return ''


del dispatch_table
del do_show_source
del do_pager
