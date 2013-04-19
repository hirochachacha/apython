#!/usr/bin/env python
#coding: utf-8

# The MIT License
#
# Copyright (c) 2009-2011 the bpython authors.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import locale
import sys
import multiprocessing
import pickle


class TimeOutException(Exception): pass


def getpreferredencoding():
    return locale.getpreferredencoding() or sys.getdefaultencoding()


def debug(s):
    import bpython
    bpython.running.clirepl.interact.notify(str(s))


class Dummy(object): pass


def _dumps(obj):
    try:
        result = pickle.dumps(obj, pickle.HIGHEST_PROTOCOL)
    except pickle.PicklingError:
        dummy = Dummy()
        dummy.class_name = obj.__class__.__name__
        dummy.__doc__ = obj.__doc__
        result = pickle.dumps(dummy, pickle.HIGHEST_PROTOCOL)
    return result


def _loads(data):
    return pickle.loads(data)


def isolate(func):
    def child_func(*args, **kwargs):
        in_ = args[0]
        try:
            data = _dumps(func(*args[1], **kwargs))
            in_.send_bytes(data)
        except Exception:
            e = sys.exc_info()[1]
            e = _dumps(e)
            in_.send_bytes(e)
        finally:
            in_.close()

    def inner(*args, **kwargs):
        out, in_ = multiprocessing.Pipe()
        _stdout = sys.stdout
        _stderr = sys.stderr
        _stdin = sys.stdin
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        sys.stdin = sys.__stdin__
        try:
            process = multiprocessing.Process(target=child_func, args=(in_, args), kwargs=kwargs)
            process.start()
            process.join(0.2)
            if process.exitcode == 0 and out.poll(0.1):
                result = _loads(out.recv_bytes())
            else:
                process.terminate()
                result = TimeOutException()
            if isinstance(result, Exception):
                raise result
        finally:
            if process.is_alive:
                process.terminate()
            sys.stdout = _stdout
            sys.stderr = _stderr
            sys.stdin = _stdin
            out.close()
        return result

    return inner


safe_eval = isolate(eval)
