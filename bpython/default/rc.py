#!/usr/bin/env python
#coding: utf-8

from plugins.editing import edit_object
from plugins.introspection import (show_source, page)

import bpython
from bpython.key.dispatch_table import dispatch_table


@dispatch_table.set_handler_on_clirepl('F2')
def do_show_source(dispatcher):
    from bpython.translations import _
    obj = dispatcher.owner.current_object
    if obj is not None:
        show_source(obj)
    else:
        dispatcher.owner.interact.notify(_('Cannot show source.'))
    return ''


@dispatch_table.set_handler_on_clirepl('F9')
def do_pager(dispatcher):
    page(dispatcher.owner.stdout)
    return ''


# @dispatch_table.set_handler_on('F8')
# def do_pastebin(self):
    # self.repl.pastebin()
    # return ''


del dispatch_table
del do_show_source
del do_pager
