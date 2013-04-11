#!/usr/bin/env python
#coding: utf-8

from __future__ import with_statement
import inspect
import tempfile
import pprint

import bpython
from bpython.repl import getpreferredencoding
from plugins.helpers import (invoke_editor, invoke_command)


__all__ = ['edit_object', 'edit_output']


def edit_object(obj):
    file_name = inspect.getsourcefile(obj)
    line_number = (inspect.findsource(obj)[-1] + 1)
    reloading = False
    editor_invocation = invoke_editor(file_name, line_number, reloading).split()
    invoke_command(editor_invocation)


def edit_output():
    with tempfile.NamedTemporaryFile() as f:
        output = bpython.running.stdout
        f.write(output.encode(getpreferredencoding()))
        f.flush()
        editor_invocation = invoke_editor(f.name, 0, False).split()
        invoke_command(editor_invocation)


def edit_output_history():
    with tempfile.NamedTemporaryFile() as f:
        entries = bpython.running.clirepl.stdout_history.entries
        output = pprint.pformat(entries)
        f.write(output.encode(getpreferredencoding()))
        f.flush()
        editor_invocation = invoke_editor(f.name, 0, False).split()
        invoke_command(editor_invocation)


def edit_input_history():
    with tempfile.NamedTemporaryFile() as f:
        entries = bpython.running.clirepl.stdin_history.entries
        output = pprint.pformat(entries)
        f.write(output.encode(getpreferredencoding()))
        f.flush()
        editor_invocation = invoke_editor(f.name, 0, False).split()
        invoke_command(editor_invocation)


def edit_history():
    with tempfile.NamedTemporaryFile() as f:
        entries = bpython.running.clirepl.history.entries
        output = pprint.pformat(entries)
        f.write(output.encode(getpreferredencoding()))
        f.flush()
        editor_invocation = invoke_editor(f.name, 0, False).split()
        invoke_command(editor_invocation)
