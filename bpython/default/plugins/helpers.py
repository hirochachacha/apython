#!/usr/bin/env python
#coding: utf-8

import inspect
import os
import re
import platform
import subprocess
import curses
import sys
import errno
from bpython.config import config


EMACS_CLIENT = re.compile(r'^emacsclient')
EMACS = re.compile(r'^emacs')
NANO = re.compile(r'^nano')
PICO = re.compile(r'^pico')
GEDIT = re.compile(r'^gedit')
KATE = re.compile(r'^kate')
VIM = re.compile(r'^[gm]vim')
VI = re.compile(r'^[gm]vi')
JEDIT = re.compile(r'^jedit')
UEDIT32 = re.compile(r'^uedit32')
GEANY = re.compile(r'^geany')
TEXTMATE = re.compile(r'^mate')
SUBLIME = re.compile(r'^subl')

is_emacs_client = lambda x: EMACS_CLIENT.match(x)
is_emacs = lambda x: EMACS.match(x)
is_nano = lambda x: NANO.match(x)
is_pico = lambda x: PICO.match(x)
is_gedit = lambda x: GEDIT.match(x)
is_kate = lambda x: KATE.match(x)
is_vim = lambda x: VIM.match(x)
is_vi = lambda x: VI.match(x)
is_jedit = lambda x: JEDIT.match(x)
is_uedit32 = lambda x: UEDIT32.match(x)
is_geany = lambda x: GEANY.match(x)
is_textmate = lambda x: TEXTMATE.match(x)
is_sublime = lambda x: SUBLIME.match(x)


class CommandError(Exception): pass


def invoke_editor(file_name, line_number, reloading):
    _editor_name = config.editor or editor_name()
    if _editor_name:
        if callable(_editor_name):
            argc = len(inspect.getargspec(config.editor).args)
            args = [file_name, line_number, reloading][:argc]
            editor_invocation = _editor_name(*args)
        elif isinstance(_editor_name, str):
            editor_invocation = "%s %s %s" % (
                _editor_name,
                blocking_flag_for_editor(_editor_name, reloading) or "",
                start_line_syntax_for_editor(_editor_name, file_name, line_number)
            )
        else:
            raise

        if editor_invocation:
            return editor_invocation
    else:
        raise (CommandError("Please set config.editor or export $VISUAL or $EDITOR"))


def blocking_flag_for_editor(_editor_name, block):
    """
    Some editors that run outside the terminal allow you to control whether or
    not to block the process from which they were launched (in this case, Pry).
    For those editors, return the flag that produces the desired behavior.
    """
    if is_emacs_client(_editor_name) and not block:
        flag = '--no-wait'
    elif is_vim(_editor_name) and block:
        flag = '--nofork'
    elif is_jedit(_editor_name) and block:
        flag = '--wait'
    elif is_textmate(_editor_name) and block:
        flag = '-w'
    elif is_sublime(_editor_name) and block:
        flag = '-w'
    else:
        flag = None
    return flag


def start_line_syntax_for_editor(_editor_name, file_name, line_number):
    """
    Return the syntax for a given editor for starting the editor
    and moving to a particular line within that file
    """

    if line_number <= 1:
        return file_name

    if is_vi(_editor_name) or \
            is_emacs(_editor_name) or \
            is_nano(_editor_name) or \
            is_pico(_editor_name) or \
            is_gedit(_editor_name) or \
            is_kate(_editor_name):
        result = "+%s %s" % (line_number, file_name)
    elif is_textmate(_editor_name) or is_geany(_editor_name):
        result = "-l %s %s" % (line_number, file_name)
    elif is_sublime(_editor_name):
        result = "%s:%s" % (file_name, line_number)
    elif is_uedit32(_editor_name):
        result = "%s/%s" % (file_name, line_number)
    elif is_jedit(_editor_name):
        result = "%s +line:%s" % (file_name, line_number)
    else:
        if platform.system() == "Windows":
            result = file_name
        else:
            result = "+%s %s" % (line_number, file_name)
    return result


def editor_name():
    """
    Get the name of the binary that Pry.config.editor points to.

    This is useful for deciding which flags we pass to the editor as
    we can just use the program's name and ignore any absolute paths.

    @example
      Pry.config.editor="/home/conrad/bin/textmate -w"
      editor_name
      # => textmate

    """
    _editor_name = os.path.basename(config.editor).split()
    if _editor_name:
        _editor_name = _editor_name[0]
    return _editor_name or os.environ.get('VISUAL') or os.environ.get('EDITOR')


def invoke_command(command):
    curses.endwin()
    try:
        subprocess.call(command)
    except OSError, e:
        raise e
    finally:
        curses.doupdate()


def invoke_command_with_input(command, inputs):
    curses.endwin()
    try:
        popen = subprocess.Popen(command, stdin=subprocess.PIPE)
        if isinstance(inputs, unicode):
            inputs = inputs.encode(sys.__stdout__.encoding, 'replace')
        popen.stdin.write(inputs)
        popen.stdin.close()
    except OSError, e:
        if e.errno == errno.ENOENT:
            # pager command not found, fall back to internal pager
            sys.stdout.write(inputs)
            return
    except IOError, e:
        if e.errno != errno.EPIPE:
            raise
    while True:
        try:
            popen.wait()
        except OSError, e:
            if e.errno != errno.EINTR:
                raise
        else:
            break
    curses.doupdate()
