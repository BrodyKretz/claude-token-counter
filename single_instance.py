"""Keep one copy of the app running.

The app can be started at login (LaunchAgent) and from Finder. A second copy
finds the lock held, asks the running copy to open its panel, and exits.
"""

import fcntl

import objc
from Foundation import NSDistributedNotificationCenter, NSObject

SHOW_PANEL_NOTIFICATION = "com.raymondtian.claudetracker.showPanel"


def acquire_lock(path):
    """Take an exclusive lock on `path`. Returns the open lock file (keep it
    open for the life of the process), or None if another process holds it."""
    lock_file = open(path, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        return None
    return lock_file


def request_show_panel():
    """Ask the already-running copy to open its panel."""
    NSDistributedNotificationCenter.defaultCenter().postNotificationName_object_userInfo_deliverImmediately_(
        SHOW_PANEL_NOTIFICATION, None, None, True
    )


class _Observer(NSObject):
    def initWithCallback_(self, callback):
        self = objc.super(_Observer, self).init()
        if self is None:
            return None
        self.callback = callback
        return self

    def showPanel_(self, _notification):
        self.callback()


def observe_show_requests(callback):
    """Call `callback` whenever another copy asks this one to open its panel.
    Returns the observer; keep a reference to it."""
    observer = _Observer.alloc().initWithCallback_(callback)
    NSDistributedNotificationCenter.defaultCenter().addObserver_selector_name_object_(
        observer, "showPanel:", SHOW_PANEL_NOTIFICATION, None
    )
    return observer
