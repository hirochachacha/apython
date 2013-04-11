#!/usr/bin/env python
#coding: utf-8

import bpython


def register_keys():
    @bpython.running.set_handler_on_clirepl('F2')
    def do_show_source(dispatcher):
        from bpython.translations import _
        from plugins.introspection import show_source
        obj = dispatcher.owner.current_object
        if obj is not None:
            show_source(obj)
        else:
            dispatcher.owner.interact.notify(_('Cannot show source.'))
        return ''

    @bpython.running.set_handler_on_clirepl('F9')
    def do_pager(dispatcher):
        from plugins.introspection import page
        page(dispatcher.owner.stdout)
        return ''


def register_command():
    from plugins.editing import (edit_object, edit_output, edit_output_history)
    from plugins.introspection import (show_source, page)

    bpython.running.register_command('%edit-object', edit_object)
    bpython.running.register_command('%edit-output', edit_output)
    bpython.running.register_command('%edit-output-history', edit_output_history)
    bpython.running.register_command('%show-source', show_source)
    bpython.running.register_command('%page', page)

    @bpython.running.register_command('p', without_completion=True)
    def p(s):
        print(s)

    @bpython.running.register_command('pp', without_completion=True)
    def pp(s):
        import pprint
        pprint.pprint(s)


register_keys()
register_command()

del register_keys
del register_command
