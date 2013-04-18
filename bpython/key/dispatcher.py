#!/usr/bin/env python
#coding: utf-8

from bpython.key.dispatch_table import (dispatch_table, CannotFindHandler)

import unicodedata
import curses

from six import u


class Dispatcher(object):
    def __init__(self, owner):
        self.owner = owner
        self.meta = False
        self.raw = False
        self.yank_index = -2
        self.previous_key = ''

        attr = "get_handler_on_%s" % owner.__class__.__name__.lower()
        self.get_handler = getattr(dispatch_table, attr)

    def run(self, key):
        if self.meta:
            try:
                key = u("M-") + u(curses.keyname(ord(key)))
            except TypeError:
                key = u("M-") + key
            self.meta = False

        if self.raw:
            result = self.do_self_insert(key)
            self.raw = False
        else:
            try:
                handler = self.get_handler(key)
                result = handler(self)
            except CannotFindHandler:
                if len(key) == 1 and not unicodedata.category(key) == 'Cc':
                    result = self.do_self_insert(key)
                else:
                    result = ''

        if not self.meta:
            self.previous_key = key
        return result

    def do_self_insert(self, key):
        self.owner.self_insert(key)
        return ''

    def smart_match(self, key, str_or_list):
        return dispatch_table.smart_match(key, str_or_list)

    # issue C-m C-a C-m C-i
    @dispatch_table.set_handler_on('C-v')
    def do_raw(self):
        self.raw = True
        return ''

    @dispatch_table.set_handler_on('KEY_BACKSPACE BACKSP')
    def do_backward_delete_character(self):
        self.owner.backward_delete_character()
        return ''

    @dispatch_table.set_handler_on('KEY_DC C-d')
    def do_delete_character(self):
        self.owner.delete_character()
        return ''

    @dispatch_table.set_handler_on('KEY_RIGHT C-f')
    def do_forward_character(self):
        self.owner.forward_character()
        return ''

    @dispatch_table.set_handler_on('KEY_LEFT C-b')
    def do_backward_character(self):
        self.owner.backward_character()
        return ''

    @dispatch_table.set_handler_on('M-b')
    def do_backward_word(self):
        self.owner.backward_word()
        return ''

    @dispatch_table.set_handler_on('M-f')
    def do_forward_word(self):
        self.owner.forward_word()
        return ''

    @dispatch_table.set_handler_on('KEY_HOME C-a')
    def do_beginning_of_line(self):
        self.owner.beginning_of_line()
        return ''

    @dispatch_table.set_handler_on('KEY_END C-e')
    def do_end_of_line(self):
        self.owner.end_of_line()
        return ''

    @dispatch_table.set_handler_on('C-k')
    def do_kill_line(self):
        self.owner.kill_line()
        return ''

    @dispatch_table.set_handler_on('C-y')
    def do_yank(self):
        self.owner.yank()
        self.yank_index = -2
        return ''

    @dispatch_table.set_handler_on('M-y')
    def do_yank_pop(self):
        if self.smart_match(self.previous_key, ['C-y', 'M-y']):
            self.owner.yank_pop(self.yank_index)
            self.yank_index -= 1
        return ''

    @dispatch_table.set_handler_on('C-w M-BACKSP')
    def do_backward_kill_word(self):
        self.owner.backward_kill_word()
        return ''

    @dispatch_table.set_handler_on('M-d')
    def do_kill_word(self):
        self.owner.kill_word()
        return ''

    @dispatch_table.set_handler_on('C-u')
    def do_backward_kill_line(self):
        self.owner.backward_kill_line()
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
    def do_accept_line(self):
        self.owner.accept_line()
        return None

    @dispatch_table.set_handler_on_clirepl('\t, C-i')
    def do_tab(self):
        return self.owner.tab()

    @dispatch_table.set_handler_on_clirepl('C-z')
    def do_suspend(self):
        return self.owner.suspend()

    # @dispatch_table.set_handler_on_clirepl('C-s')
    # def do_save(self):
        # self.owner.write2file()
        # return ''

    @dispatch_table.set_handler_on_clirepl(r'KEY_PPAGE \S M-<')
    def do_beginning_of_history(self):
        self.owner.beginning_of_history()
        return ''

    @dispatch_table.set_handler_on_clirepl(r'KEY_NPAGE \T M->')
    def do_end_of_history(self):
        self.owner.end_of_history()
        return ''

    @dispatch_table.set_handler_on_clirepl('C-l')
    def do_clear_screen(self):
        self.owner.clear_screen()
        return ''

    @dispatch_table.set_handler_on_clirepl('C-_')
    def do_undo(self):
        self.owner.undo()
        return ''

    @dispatch_table.set_handler_on_clirepl('C-s')
    def do_search_history(self):
        if self.owner.in_search_mode == "search" and self.owner.s:
            self.owner.show_next_page()
        # elif self.owner.in_search_mode == "reverse" and self.owner.s:
            # pass
        else:
            self.owner.search_history()
        return ''

    @dispatch_table.set_handler_on_clirepl('C-r')
    def do_reverse_search_history(self):
        if self.owner.in_search_mode == "reverse" and self.owner.s:
            self.owner.show_next_page()
        # elif self.owner.in_search_mode == "search" and self.owner.s:
            # pass
        else:
            self.owner.reverse_search_history()
        return ''

    @dispatch_table.set_handler_on_clirepl('C-x')
    def debug(self):
        from bpython.cli import debug
        debug(str(self.owner.current_word)
                + ':'
                + str(self.owner.current_line)
                + ':'
                + str(self.owner.matches))
        return ''

    @dispatch_table.set_handler_on_clirepl('M-. M-_')
    def do_insert_last_argument(self):
        self.owner.insert_last_argument()
        return ''

    @dispatch_table.set_handler_on_clirepl('KEY_UP C-p')
    def do_previous_history(self):
        self.owner.previous_history()
        return ''

    @dispatch_table.set_handler_on_clirepl('KEY_DOWN C-n')
    def do_next_history(self):
        self.owner.next_history()
        return ''

    @dispatch_table.set_handler_on_clirepl('C-d')
    def do_delete_character_or_exit(self):
        if not self.owner.s:
            self.owner.do_exit = True
            return None
        else:
            self.owner.delete_character()
            return ''

    @dispatch_table.set_handler_on_clirepl('C_BACK')
    def do_cbackspace(self):
        self.owner.backward_kill_line()
        return self.run('\n')

    @dispatch_table.set_handler_on_clirepl('ESC')
    def do_prefix_meta(self):
        if self.owner.in_search_mode:
            self.owner.exit_search_mode()
        else:
            self.meta = True
        return ''

    @dispatch_table.set_handler_on_statusbar('ESC')
    def do_cancel(self):
        self.owner.backward_kill_line()
        return self.run('\n')
