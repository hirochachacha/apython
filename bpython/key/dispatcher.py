#!/usr/bin/env python
#coding: utf-8

from bpython.key.dispatch_table import (dispatch_table, CannotFindHandler)
from bpython.pager import page
from bpython.translations import _

import unicodedata
import platform


class Dispatcher(object):
    def __init__(self, repl):
        self.repl = repl
        self.meta = False

    def run(self, key):
        if self.meta:
            if len(key) == 1 and not unicodedata.category(key) == 'Cc':
                key = "M-%s" % key
            self.meta = False

        try:
            handler = dispatch_table.get_handler_on(key)
            return handler(self)
        except CannotFindHandler:
            if len(key) == 1 and not unicodedata.category(key) == 'Cc':
                return self.do_normal(key)
            else:
                return ''

    def do_normal(self, key):
        self.repl.addstr(key)
        self.repl.print_line(self.repl.s)
        return ''

    @dispatch_table.set_handler_on('ESC')
    def do_escape(self):
        self.meta = True
        return ''

    @dispatch_table.set_handler_on('C_BACK')
    def do_cbackspace(self):
        self.repl.clrtobol()
        return self.run('\n')

    @dispatch_table.set_handler_on('KEY_BACKSPACE BACKSP')
    def do_backspace(self):
        self.repl.bs()
        self.repl.complete()
        return ''

    @dispatch_table.set_handler_on('KEY_DC')
    def do_delete(self):
        self.repl.delete()
        self.repl.complete()
        self.repl.print_line(self.repl.s)
        return ''

    @dispatch_table.set_handler_on('C-d')
    def do_delete_or_exit(self):
        if not self.repl.s:
            # Delete on empty line exits
            self.repl.do_exit = True
            return None
        else:
            return self.do_delete()

    @dispatch_table.set_handler_on('C-r')
    def do_undo(self):
        self.repl.undo()
        return ''

    @dispatch_table.set_handler_on('C-o')
    def do_search(self):
        self.repl.search()
        return ''

    @dispatch_table.set_handler_on('KEY_UP C-p')
    def do_up(self):
        self.repl.back()
        return ''

    @dispatch_table.set_handler_on('KEY_DOWN C-n')
    def do_down(self):
        self.repl.fwd()
        return ''

    @dispatch_table.set_handler_on('KEY_LEFT C-b')
    def do_left(self):
        self.repl.mvc(1)
        self.repl.print_line(self.repl.s)
        return ''

    @dispatch_table.set_handler_on('KEY_RIGHT C-f')
    def do_right(self):
        self.repl.mvc(-1)
        self.repl.print_line(self.repl.s)
        return ''

    @dispatch_table.set_handler_on('KEY_HOME C-a')
    def do_home(self):
        self.repl.home()
        self.repl.print_line(self.repl.s)
        return ''

    @dispatch_table.set_handler_on('KEY_END C-e')
    def do_end(self):
        self.repl.end()
        self.repl.print_line(self.repl.s)
        return ''

    @dispatch_table.set_handler_on(r'KEY_NPAGE \T')
    def do_next_page(self):
        self.repl.hend()
        self.repl.print_line(self.repl.s)
        return ''

    @dispatch_table.set_handler_on(r'KEY_PPAGE \S')
    def do_previous_page(self):
        self.repl.hbegin()
        self.repl.print_line(self.repl.s)
        return ''

    @dispatch_table.set_handler_on('C-k')
    def do_kill_line(self):
        self.repl.cut_to_buffer()
        return ''

    @dispatch_table.set_handler_on('C-y')
    def do_yank(self):
        self.repl.yank_from_buffer()
        return ''

    @dispatch_table.set_handler_on('C-w')
    def do_cut_word(self):
        self.repl.cut_buffer = self.repl.bs_word()
        self.repl.complete()
        return ''

    @dispatch_table.set_handler_on('C-u')
    def do_cut_head(self):
        self.repl.clrtobol()
        return ''

    @dispatch_table.set_handler_on('C-l')
    def do_clear_screen(self):
        self.repl.s_hist = [self.repl.s_hist[-1]]
        self.repl.highlighted_paren = None
        self.repl.redraw()
        return ''

    def do_exit_(self):
        if not self.repl.s:
            self.repl.do_exit = True
            return None
        else:
            return ''

    @dispatch_table.set_handler_on('C-s')
    def do_save(self):
        self.repl.write2file()
        return ''

    @dispatch_table.set_handler_on('F8')
    def do_pastebin(self):
        self.repl.pastebin()
        return ''

    @dispatch_table.set_handler_on('F9')
    def do_pager(self):
        page(self.repl.stdout_hist[self.repl.prev_block_finished:-4])
        return ''

    @dispatch_table.set_handler_on('F2')
    def do_show_source(self):
        source = self.repl.get_source_of_current_name()
        if source is not None:
            page(source, use_hilight=self.repl.config.highlight_show_source)
        else:
            self.repl.statusbar.message(_('Cannot show source.'))
        return ''

    @dispatch_table.set_handler_on('\n \r PADENTER')
    def do_newline(self):
        self.repl.lf()
        return None

    @dispatch_table.set_handler_on('\t')
    def do_tab(self):
        return self.repl.tab()

    @dispatch_table.set_handler_on('KEY_BTAB')
    def do_backtab(self):
        return self.repl.tab(back=True)

    @dispatch_table.set_handler_on('C-z')
    def do_suspend(self):
        if platform.system() != 'Windows':
            self.repl.suspend()
            return ''
        else:
            self.repl.do_exit = True
            return None

    @dispatch_table.set_handler_on('PADMINUS')
    def do_padminus(self):
        return self.run('-')

    @dispatch_table.set_handler_on('PADPLUS')
    def do_padplus(self):
        return self.run('+')

    @dispatch_table.set_handler_on('PADSLASH')
    def do_padslash(self):
        return self.run('/')

    @dispatch_table.set_handler_on('PADSTAR')
    def do_padstar(self):
        return self.run('*')
