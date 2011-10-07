# Author of the original function: John P. Speno

import signal

class TimeoutException(Exception):
    """Exception to raise on a timeout."""
    pass

class Timeout:
    def __init__(self, function, timeout):
        self.timeout = timeout
        self.function = function

    def handle_timeout(self, signum, frame):
        raise TimeoutException()

    def __call__(self, *args):
        old = signal.signal(signal.SIGALRM, self.handle_timeout)
        signal.alarm(self.timeout)
        try:
            result = self.function(*args)
        finally:
            signal.signal(signal.SIGALRM, old)
        signal.alarm(0)
        return result

