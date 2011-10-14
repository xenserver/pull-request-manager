import signal

class Watchdog(Exception):
  def __init__(self, time=5):
    self.time = time

  def __enter__(self):
    signal.signal(signal.SIGALRM, self.handler)
    signal.alarm(self.time)

  def __exit__(self, type, value, traceback):
    signal.alarm(0)

  def handler(self, signum, frame):
    raise self

  def __str__(self):
    return "The code you executed took more than %ds to complete" % self.time
