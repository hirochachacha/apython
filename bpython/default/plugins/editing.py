#!/usr/bin/env python
#coding: utf-8

from plugins.helpers import (invoke_editor, invoke_command)
import inspect


def edit_object(obj):
    file_name = inspect.getsourcefile(obj)
    line_number = (inspect.findsource(obj)[-1] + 1)
    reloading = False
    editor_invocation = invoke_editor(file_name, line_number, reloading).split()
    invoke_command(editor_invocation)
