# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy

def force_redraw():
  for window in bpy.context.window_manager.windows:
    screen = getattr(window, "screen", None)
    if not screen:
      continue
    for area in screen.areas:
      area.tag_redraw()
  try:
    bpy.context.view_layer.update()
  except Exception:
    pass

class ProgressHelper:
  def __init__(self):
    self.wm = bpy.context.window_manager
    self.total = 0
    self.cur = 0
    self.started = False

  def begin(self, total, msg="BeamNGLevelImporter: working..."):
    self.total = max(1, int(total))
    self.cur = 0
    self.started = True
    try:
      self.wm.progress_begin(0, self.total)
    except Exception:
      pass
    try:
      bpy.context.window.cursor_set('WAIT')
    except Exception:
      pass
    print(msg)
    force_redraw()

  def update(self, msg=None, step=1):
    if not self.started:
      return
    self.cur = min(self.total, self.cur + max(1, int(step)))
    try:
      self.wm.progress_update(self.cur)
    except Exception:
      pass
    if msg:
      print(str(msg))
    force_redraw()

  def end(self, msg_done="BeamNGLevelImporter: done"):
    if not self.started:
      return
    try:
      self.wm.progress_update(self.total)
    except Exception:
      pass
    try:
      self.wm.progress_end()
    except Exception:
      pass
    print(msg_done)
    force_redraw()
    try:
      bpy.context.window.cursor_set('DEFAULT')
    except Exception:
      pass
    self.started = False