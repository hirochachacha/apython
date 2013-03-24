#!/usr/bin/env python
#coding: utf-8

from plugins.editing import edit_object
from plugins.introspection import (show_source, page)

from bpython.config import config
from bpython.key.dispatch_table import dispatch_table
from bpython.key.dispatcher import Dispatcher
from bpython.translations import _


class CustomDispatcher(Dispatcher):
    @dispatch_table.set_handler_on('F2')
    def do_show_source(self):
        obj = self.repl.get_current_object()
        if obj is not None:
            show_source(obj)
        else:
            self.repl.statusbar.message(_('Cannot show source.'))
        return ''

    @dispatch_table.set_handler_on('F9')
    def do_pager(self):
        page(self.repl.stdout_hist[self.repl.prev_block_finished:-4])
        return ''


config.dispatcher = CustomDispatcher
