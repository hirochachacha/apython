#!/usr/bin/env python
#coding: utf-8

import re
import ast


WORD = re.compile(r'([\w\\.\-\\%])+')


def get_rclosure(s, ignore_quote=False):
    if not s:
        return None
    line = list(s)
    c = line.pop()
    sp = {"'": 0, '"': 0, ')': 0, ']': 0, '}': 0}
    recent_paren_or_bracket = []
    if ignore_quote:
        is_in_squote = lambda: False
        is_in_dquote = lambda: False
    else:
        is_in_squote = lambda: bool(sp["'"])
        is_in_dquote = lambda: bool(sp['"'])
    is_in_paren = lambda: bool(sp[')'])
    is_in_sbracket = lambda: bool(sp[']'])
    is_in_cbracket = lambda: bool(sp['}'])
    is_close = lambda: not (is_in_paren() or is_in_sbracket() or is_in_squote() or is_in_dquote() or is_in_cbracket())
    if c in sp:
        if c == ')':
            recent_paren_or_bracket.append(')')
        elif c == ']':
            recent_paren_or_bracket.append(']')
        elif c == '}':
            recent_paren_or_bracket.append('}')
        sp[c] += 1
    else:
        return None
    while line:
        c = line.pop()
        if is_close():
            break
        elif is_in_squote():
            if c == "'":
                sp["'"] -= 1
            else:
                pass
        elif is_in_dquote():
            if c == '"':
                sp['"'] -= 1
            else:
                pass
        elif is_in_paren() and (not recent_paren_or_bracket or recent_paren_or_bracket[-1] == ')'):
            if c == '(':
                sp[')'] -= 1
                recent_paren_or_bracket.pop()
            elif c == '[':
                return None
            elif c == '{':
                return None
            elif c == ')':
                sp[')'] += 1
                recent_paren_or_bracket.append(')')
            elif c == ']':
                sp[']'] += 1
                recent_paren_or_bracket.append(']')
            elif c == '}':
                sp['}'] += 1
                recent_paren_or_bracket.append('}')
            elif c == "'":
                sp["'"] += 1
            elif c == '"':
                sp['"'] += 1
            else:
                pass
        elif is_in_sbracket() and (not recent_paren_or_bracket or recent_paren_or_bracket[-1] == ']'):
            if c == '[':
                sp[']'] -= 1
                recent_paren_or_bracket.pop()
            elif c == '(':
                return None
            elif c == '{':
                return None
            elif c == ')':
                sp[')'] += 1
                recent_paren_or_bracket.append(')')
            elif c == ']':
                sp[']'] += 1
                recent_paren_or_bracket.append(']')
            elif c == '}':
                sp['}'] += 1
                recent_paren_or_bracket.append('}')
            elif c == "'":
                sp["'"] += 1
            elif c == '"':
                sp['"'] += 1
            else:
                pass
        elif is_in_cbracket() and (not recent_paren_or_bracket or recent_paren_or_bracket[-1] == '}'):
            if c == '{':
                sp['}'] -= 1
                recent_paren_or_bracket.pop()
            elif c == '(':
                return None
            elif c == '[':
                return None
            elif c == ')':
                sp[')'] += 1
                recent_paren_or_bracket.append(')')
            elif c == ']':
                sp[']'] += 1
                recent_paren_or_bracket.append(']')
            elif c == '}':
                sp['}'] += 1
                recent_paren_or_bracket.append('}')
            elif c == "'":
                sp["'"] += 1
            elif c == '"':
                sp['"'] += 1
            else:
                pass
        else:
            pass
    else:
        if is_close():
            return s[-len(s) + len(line):]
        else:
            return None
    return s[-len(s) + len(line) + 1:]


def get_rword(line):
    if not (line and WORD.match(line[-1])):
        return None

    l = len(line)

    i = 1
    for i in xrange(1, l + 1):
        if not WORD.match(line[-i]):
            i -= 1
            break

    return line[-i:]


def get_rclosure_word(line):
    chunk = ''
    while True:
        rword = get_rword(line)
        if rword:
            chunk = rword + chunk
            line = line[:-len(rword)]

        rclosure = get_rclosure(line)
        if rclosure:
            chunk = rclosure + chunk
            line = line[:-len(rclosure)]

        if not (rword or rclosure):
            break
    return chunk


def get_rfunc(line):
    line = line + ')'
    closure = get_rclosure(line)
    if closure:
        args = get_args(closure)
        return get_rclosure_word(line[:-len(closure)]), args
    else:
        return None, []


def get_rsbracket(line):
    line = line + ']'
    closure = get_rclosure(line, ignore_quote=True)
    if closure:
        return get_rclosure_word(line[:-len(closure)]), closure[1:-1]
    else:
        return None, None


def get_args(paren_closure):
    result = []
    line = paren_closure[:-1].rstrip(' ')
    if line == '(':
        return result
    word = get_rclosure_word(line)
    if word:
        result.insert(0, word)
        line = line[:-len(word)].rstrip(' ')
        if line:
            if line[-1] == ',':
                line = line[:-1].rstrip(' ')
            if line[-1] == '=':
                line = line[:-1].rstrip(' ')
                word = get_rclosure_word(line)
                if word:
                    result[0] = word + '=' + result[0]
                else:
                    return None
            elif line == '(':
                return result
    else:
        result.insert(0, None)
        line = line.rstrip(' ')
        if line:
            if line[-1] == ',':
                line = line[:-1].rstrip(' ')
            if line[-1] == '=':
                line = line[:-1].rstrip(' ')
                word = get_rclosure_word(line)
                if word:
                    result[0] = word + '='
                else:
                    return None
            elif line == '(':
                return result
    while True:
        word = get_rclosure_word(line)
        if word:
            result.insert(0, word)
            line = line[:-len(word)].rstrip(' ')
            if line:
                if line[-1] == ',':
                    line = line[:-1].rstrip(' ')
                if line[-1] == '=':
                    line = line[:-1].rstrip(' ')
                    word = get_rclosure_word(line)
                    if word:
                        result[0] = word + '=' + result[0]
                    else:
                        return None
                elif line == '(':
                    return result
        else:
            return None


def get_closure_words(line):
    result = []
    while True:
        word = get_rclosure_word(line)
        if word:
            result.insert(0, word)
            line = line[:-len(word)].rstrip(' ')
        else:
            if line:
                return []
            else:
                return result


def is_only_word(line):
    return line == get_rword(line)


def is_assignment_statement(line):
    try:
        main_ast = ast.parse(line)
        if isinstance(main_ast.body[0], ast.Assign):
            return True
    except SyntaxError:
        return False
    return False
