# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import re
from pathlib import Path

def decode_sjson_text(text: str):
  ws = set(' \r\n\t,')
  number_re = re.compile(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')
  bareword_re = re.compile(r'[A-Za-z0-9_@$\+\-]+')
  escapes = {'t':'\t', 'n':'\n', 'f':'\f', 'r':'\r', 'b':'\b', '\\':'\\', '"':'"', '/':'/', "\n":"\n"}

  def skip_ws(s, i):
    l = len(s)
    while i < l:
      c = s[i]
      if c in ws:
        i += 1
      elif c == '/':
        if i+1 < l and s[i+1] == '/':
          i += 2
          while i < l and s[i] not in '\n\r':
            i += 1
        elif i+1 < l and s[i+1] == '*':
          i += 2
          while i+1 < l and not (s[i] == '*' and s[i+1] == '/'):
            i += 1
          i += 2
        else:
          break
      else:
        break
    return i

  def parse_number(s, i):
    m = number_re.match(s, i)
    if not m: raise ValueError("Invalid number")
    val = m.group(0)
    try:
      return (float(val) if ('.' in val or 'e' in val or 'E' in val) else int(val)), m.end()
    except Exception:
      if val in ['1#INF00', '+1#INF00']:
        return float('inf'), m.end()
      if val == '-1#INF00':
        return -float('inf'), m.end()
      raise

  def parse_string(s, i):
    assert s[i] == '"'
    i += 1
    res = []
    l = len(s)
    while i < l:
      ch = s[i]
      if ch == '"':
        return ''.join(res), i+1
      if ch == '\\':
        i += 1
        esc = s[i]
        if esc == 'u':
          res.append(chr(int(s[i+1:i+5],16))); i += 5; continue
        elif esc in escapes:
          res.append(escapes[esc])
        else:
          res.append(esc)
        i += 1; continue
      res.append(ch); i += 1
    raise ValueError("Unterminated string")

  def parse_key(s, i):
    i = skip_ws(s, i)
    if s[i] == '"':
      return parse_string(s, i)
    m = bareword_re.match(s, i)
    if not m: raise ValueError("Invalid key")
    return m.group(0), m.end()

  def parse_value(s, i):
    i = skip_ws(s, i)
    c = s[i]
    if c == '{': return parse_object(s, i)
    if c == '[': return parse_array(s, i)
    if c == '"': return parse_string(s, i)
    if s.startswith('true', i): return True, i+4
    if s.startswith('false', i): return False, i+5
    if s.startswith('null', i): return None, i+4
    if c.isdigit() or c in '+-.': return parse_number(s, i)
    m = bareword_re.match(s, i)
    if m:
      val = m.group(0)
      if val == 'true': return True, m.end()
      if val == 'false': return False, m.end()
      if val == 'null': return None, m.end()
      return val, m.end()
    raise ValueError("Invalid value")

  def parse_object(s, i):
    assert s[i] == '{'
    i += 1
    obj = {}
    i = skip_ws(s, i)
    while i < len(s) and s[i] != '}':
      key, i = parse_key(s, i)
      i = skip_ws(s, i)
      if i < len(s) and s[i] in ':=': i += 1
      else: raise ValueError("Missing : or =")
      val, i = parse_value(s, i)
      obj[key] = val
      i = skip_ws(s, i)
      if i < len(s) and s[i] == ',': i += 1
      i = skip_ws(s, i)
    if i >= len(s) or s[i] != '}': raise ValueError("Expected }")
    return obj, i+1

  def parse_array(s, i):
    assert s[i] == '['
    i += 1
    arr = []
    l = len(s)
    i = skip_ws(s, i)
    while i < l and s[i] != ']':
      val, i = parse_value(s, i)
      arr.append(val)
      i = skip_ws(s, i)
      if i < l and s[i] == ',': i += 1
      i = skip_ws(s, i)
    if i >= l or s[i] != ']': raise ValueError("Expected ]")
    return arr, i+1

  s = text
  i = skip_ws(s, 0)
  val, i = parse_value(s, i)
  i = skip_ws(s, i)
  if i != len(s): raise ValueError("Trailing text")
  return val

def decode_sjson_file(path: Path):
  with open(path, 'r', encoding='utf-8') as f:
    return decode_sjson_text(f.read())

def read_json_records(path: Path):
  items = []
  try:
    data = decode_sjson_file(path)
    if isinstance(data, list):
      return list(data)
    if isinstance(data, dict):
      return [data]
    with open(path, 'r', encoding='utf-8') as f:
      for line in f:
        line = line.strip()
        if not line:
          continue
        try:
          items.append(decode_sjson_text(line))
        except Exception:
          pass
  except Exception:
    try:
      with open(path, 'r', encoding='utf-8') as f:
        for line in f:
          line = line.strip()
          if not line:
            continue
          try:
            items.append(decode_sjson_text(line))
          except Exception:
            pass
    except Exception:
      pass
  return items
