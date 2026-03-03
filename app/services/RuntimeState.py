class RuntimeState:
  def __init__(self):
    self.sleep_mode = False

  def set_sleep_mode(self, enabled: bool):
    self.sleep_mode = enabled

  def is_sleep_mode(self) -> bool:
    return self.sleep_mode
