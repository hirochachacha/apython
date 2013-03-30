#!/usr/bin/env python
#coding: utf-8

from bpython.key.dispatch_table import (dispatch_table, CannotFindHandler)

import unicodedata
import platform


class Dispatcher(object):
    def __init__(self, owner):
        self.owner = owner
        self.meta = False
        self.raw = False

        attr = "get_handler_on_%s" % owner.__class__.__name__.lower()
        self.get_handler = getattr(dispatch_table, attr)

    def run(self, key):
        if self.meta:
            if len(key) == 1 and not unicodedata.category(key) == 'Cc':
                key = "M-%s" % key
            self.meta = False

        if self.raw:
            self.raw = False
            return self.do_normal(key)

        try:
            handler = self.get_handler(key)
            return handler(self)
        except CannotFindHandler:
            if len(key) == 1 and not unicodedata.category(key) == 'Cc':
                return self.do_normal(key)
            else:
                return ''

    def do_normal(self, key):
        self.owner.addstr(key)
        self.owner.print_line(self.owner.s)
        return ''

    @dispatch_table.set_handler_on('ESC')
    def do_escape(self):
        self.meta = True
        return ''

    # C-aとC-mで文字が表示されない
    # do_left, do_rightの際に2文字分移動する必要が有る
    # do_deleteの際に2文字分移動する必要が有る
    # (1..31)までのascii
    # @dispatch_table.set_handler_on('C-v')
    # def do_raw(self):
        # self.raw = True
        # return ''

    @dispatch_table.set_handler_on('KEY_BACKSPACE BACKSP')
    def do_backspace(self):
        self.owner.bs()
        return ''

    @dispatch_table.set_handler_on('KEY_DC C-d')
    def do_delete(self):
        self.owner.delete()
        return ''

    @dispatch_table.set_handler_on('KEY_LEFT C-b')
    def do_left(self):
        self.owner.mvc(1)
        self.owner.print_line(self.owner.s)
        return ''

    @dispatch_table.set_handler_on('KEY_RIGHT C-f')
    def do_right(self):
        self.owner.mvc(-1)
        self.owner.print_line(self.owner.s)
        return ''

    @dispatch_table.set_handler_on('KEY_HOME C-a')
    def do_home(self):
        self.owner.home()
        return ''

    @dispatch_table.set_handler_on('KEY_END C-e')
    def do_end(self):
        self.owner.end()
        return ''

    @dispatch_table.set_handler_on('C-k')
    def do_kill_line(self):
        self.owner.cut_to_buffer()
        return ''

    @dispatch_table.set_handler_on('C-y')
    def do_yank(self):
        self.owner.yank_from_buffer()
        return ''

    @dispatch_table.set_handler_on('C-w')
    def do_cut_word(self):
        self.owner.bs_word()
        return ''

    @dispatch_table.set_handler_on('C-u')
    def do_cut_head(self):
        self.owner.cut_to_head()
        return ''

    @dispatch_table.set_handler_on('KEY_BTAB')
    def do_backtab(self):
        return self.owner.tab(back=True)

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

    @dispatch_table.set_handler_on('\n \r PADENTER')
    def do_newline(self):
        self.owner.lf()
        return None

    @dispatch_table.set_handler_on_clirepl('\t, C-i')
    def do_tab(self):
        return self.owner.tab()

    @dispatch_table.set_handler_on_clirepl('C-z')
    def do_suspend(self):
        if platform.system() != 'Windows':
            self.owner.suspend()
            return ''
        else:
            self.owner.do_exit = True
            return None

    @dispatch_table.set_handler_on_clirepl('C-s')
    def do_save(self):
        self.owner.write2file()
        return ''

    @dispatch_table.set_handler_on_clirepl(r'KEY_NPAGE \T')
    def do_next_page(self):
        self.owner.hend()
        self.owner.print_line(self.owner.s)
        return ''

    @dispatch_table.set_handler_on_clirepl(r'KEY_PPAGE \S')
    def do_previous_page(self):
        self.owner.hbegin()
        self.owner.print_line(self.owner.s)
        return ''

    @dispatch_table.set_handler_on_clirepl('C-l')
    def do_clear_screen(self):
        self.owner.s_hist = [self.owner.s_hist[-1]]
        self.owner.highlighted_paren = None
        self.owner.redraw()
        return ''

    @dispatch_table.set_handler_on_clirepl('C-r')
    def do_undo(self):
        self.owner.undo()
        return ''

    @dispatch_table.set_handler_on_clirepl('C-o')
    def do_search(self):
        self.owner.search()
        return ''

    @dispatch_table.set_handler_on_clirepl('KEY_UP C-p')
    def do_up(self):
        self.owner.back()
        return ''

    @dispatch_table.set_handler_on_clirepl('KEY_DOWN C-n')
    def do_down(self):
        self.owner.fwd()
        return ''

    @dispatch_table.set_handler_on_clirepl('C-d')
    def do_delete_or_exit(self):
        if not self.owner.s:
            # Delete on empty line exits
            self.owner.do_exit = True
            return None
        else:
            self.owner.delete()
            self.owner.complete()
            self.owner.print_line(self.owner.s)
            return ''

    @dispatch_table.set_handler_on_clirepl('C_BACK')
    def do_cbackspace(self):
        self.owner.cut_to_head()
        return self.run('\n')

    @dispatch_table.set_handler_on_statusbar('ESC')
    def do_cancel_statusbar(self):
        self.owner.cut_to_head()
        return self.run('\n')
