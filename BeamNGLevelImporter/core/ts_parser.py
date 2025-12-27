# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import re

_TOKEN_WS = re.compile(r'\s+')
_TOKEN_ID = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
_TOKEN_NUM = re.compile(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')
_BAREWORD = re.compile(r'[A-Za-z0-9_@$\+\-]+')

class _Tok:
  def __init__(self, kind, val, line, col):
    self.kind = kind
    self.val = val
    self.line = line
    self.col = col

def _tokenize(text):
  i = 0; n = len(text); line=0; col=0
  def adv(k=1):
    nonlocal i, col
    i += k; col += k
  def newline():
    nonlocal line, col
    line += 1; col = 0
  while i < n:
    c = text[i]
    if c in ' \t\r':
      m = _TOKEN_WS.match(text, i)
      adv(m.end()-i)
      continue
    if c == '\n':
      newline(); adv(1); continue
    if c == '/' and i+1 < n and text[i+1] == '/':
      while i < n and text[i] != '\n':
        adv(1)
      continue
    if c == '/' and i+1 < n and text[i+1] == '*':
      adv(2)
      while i+1 < n and not (text[i] == '*' and text[i+1] == '/'):
        if text[i] == '\n': newline()
        adv(1)
      adv(2)
      continue
    if c in '(){};=:,':
      yield _Tok('sym', c, line, col); adv(1); continue
    if c == '"':
      j=i+1; buf=[]
      while j < n:
        if text[j] == '\\' and j+1 < n:
          esc = text[j+1]
          if esc == 'n': buf.append('\n'); j += 2; continue
          if esc == 't': buf.append('\t'); j += 2; continue
          buf.append(text[j+1]); j += 2; continue
        if text[j] == '"':
          s = ''.join(buf)
          yield _Tok('str', s, line, col); col += (j-i+1); i=j+1
          break
        buf.append(text[j]); j+=1
      else:
        yield _Tok('str', ''.join(buf), line, col); i = j
      continue
    m = _TOKEN_NUM.match(text, i)
    if m:
      yield _Tok('num', m.group(0), line, col); adv(m.end()-i); continue
    m = _TOKEN_ID.match(text, i)
    if m:
      yield _Tok('id', m.group(0), line, col); adv(m.end()-i); continue
    m = _BAREWORD.match(text, i)
    if m:
      yield _Tok('id', m.group(0), line, col); adv(m.end()-i); continue
    # fallback
    yield _Tok('sym', c, line, col); adv(1)

def _parse_array_or_scalar(tok, i):
  if i < len(tok) and tok[i].kind == 'sym' and tok[i].val == '[':
    i += 1; vals=[]
    while i < len(tok) and not (tok[i].kind=='sym' and tok[i].val==']'):
      v, i = _parse_value(tok, i)
      vals.append(v)
      if i < len(tok) and tok[i].kind=='sym' and tok[i].val==',':
        i += 1
    if i < len(tok) and tok[i].kind=='sym' and tok[i].val==']':
      i += 1
    return vals, i
  return None, i

def _parse_value(tok, i):
  if i >= len(tok): return None, i
  t = tok[i]
  if t.kind == 'str':
    return t.val, i+1
  if t.kind == 'num':
    s = t.val
    try:
      if '.' in s or 'e' in s or 'E' in s: return float(s), i+1
      return int(s), i+1
    except: return s, i+1
  if t.kind == 'id':
    if t.val in ('true','false','True','False'): return (t.val[0].lower()=='t'), i+1
    if t.val == 'null' or t.val == 'NULL': return None, i+1
    return t.val, i+1
  if t.kind=='sym' and t.val=='(':
    # support vector-like (x y z) -> [x,y,z]
    i += 1; vals=[]
    while i < len(tok) and not (tok[i].kind=='sym' and tok[i].val==')'):
      v, i = _parse_value(tok, i)
      if v is not None: vals.append(v)
      if i < len(tok) and tok[i].kind=='sym' and tok[i].val==',':
        i += 1
    if i < len(tok) and tok[i].kind=='sym' and tok[i].val==')': i += 1
    return vals, i
  arr, j = _parse_array_or_scalar(tok, i)
  if arr is not None: return arr, j
  return None, i+1

def parse_torque_file(text):
  tok = list(_tokenize(text))
  i = 0
  objects = []
  stack = []

  def parse_object(i, parent):
    # new/singleton/datablock
    if i >= len(tok) or not (tok[i].kind=='id' and tok[i].val in ('new','singleton','datablock')):
      return None, i
    i += 1
    # class
    cls = tok[i].val if (i < len(tok) and tok[i].kind in ('id','str')) else 'SimObject'
    i += 1
    # '(' name [ ':' copy ] ')'
    if i < len(tok) and tok[i].kind=='sym' and tok[i].val=='(':
      i += 1
      name = ''
      if i < len(tok) and tok[i].kind in ('id','str'):
        name = tok[i].val; i += 1
        if i < len(tok) and tok[i].kind=='sym' and tok[i].val==':':
          i += 1
          # skip copy source
          if i < len(tok): i += 1
      # skip to ')'
      while i < len(tok) and not (tok[i].kind=='sym' and tok[i].val==')'):
        i += 1
      if i < len(tok): i += 1
    else:
      name = ''

    obj = { 'class': cls }
    if name: obj['name'] = name
    if parent and parent.get('name'):
      obj['__parent'] = parent['name']
    # ';' or '{'
    if i < len(tok) and tok[i].kind=='sym' and tok[i].val==';':
      i += 1
      objects.append(obj)
      return obj, i
    if i < len(tok) and tok[i].kind=='sym' and tok[i].val=='{':
      i += 1
      while i < len(tok) and not (tok[i].kind=='sym' and tok[i].val=='}'):
        # nested object?
        if tok[i].kind=='id' and tok[i].val in ('new','singleton','datablock'):
          child, i = parse_object(i, obj)
          continue
        # prop = value ;
        if tok[i].kind in ('id','str'):
          key = tok[i].val; i += 1
          # array prop? foo[3]
          if i < len(tok) and tok[i].kind=='sym' and tok[i].val=='[':
            # skip until ']'
            while i < len(tok) and not (tok[i].kind=='sym' and tok[i].val==']'):
              i += 1
            if i < len(tok): i += 1
          # '='
          if i < len(tok) and tok[i].kind=='sym' and tok[i].val=='=':
            i += 1
            val, i = _parse_value(tok, i)
            # skip until ';'
            while i < len(tok) and not (tok[i].kind=='sym' and tok[i].val==';'):
              i += 1
            if i < len(tok): i += 1
            obj[key] = val
            continue
        i += 1
      if i < len(tok) and tok[i].kind=='sym' and tok[i].val=='}':
        i += 1
      # optional ';'
      if i < len(tok) and tok[i].kind=='sym' and tok[i].val==';':
        i += 1
      objects.append(obj)
      return obj, i
    # malformed
    objects.append(obj)
    return obj, i

  parent = None
  while i < len(tok):
    if tok[i].kind=='id' and tok[i].val in ('new','singleton','datablock'):
      _, i = parse_object(i, parent)
    else:
      i += 1
  return objects