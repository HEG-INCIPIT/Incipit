# =============================================================================
#
# EZID :: status.py
#
# Periodic status reporting.
#
# This module should be imported at server startup so that its daemon
# thread is started.
#
# Author:
#   Greg Janee <gjanee@ucop.edu>
#
# License:
#   Copyright (c) 2013, Regents of the University of California
#   http://creativecommons.org/licenses/BSD/
#
# -----------------------------------------------------------------------------

import os
import threading
import time
import uuid

import config
import datacite
import ezid
import log
import search
import store

_reportingInterval = None
_threadName = None

def _formatUserCountList (d):
  if len(d) > 0:
    l = d.items()
    l.sort(cmp=lambda x, y: -cmp(x[1], y[1]))
    return " (" + " ".join("%s=%d" % i for i in l) + ")"
  else:
    return ""

def _statusDaemon ():
  while threading.currentThread().getName() == _threadName:
    try:
      activeUsers, waitingUsers = ezid.getStatus()
      na = sum(activeUsers.values())
      nw = sum(waitingUsers.values())
      nstc, nstca = store.numConnections()
      nsec, nseca = search.numConnections()
      log.status("pid=%d" % os.getpid(),
        "threads=%d" % threading.activeCount(),
        "activeOperations=%d%s" % (na, _formatUserCountList(activeUsers)),
        "waitingRequests=%d%s" % (nw, _formatUserCountList(waitingUsers)),
        "dataciteOperations=%d" % datacite.numActiveOperations(),
        "active/storeDatabaseConnections=%d/%d" % (nstca, nstc),
        "active/searchDatabaseConnections=%d/%d" % (nseca, nsec))
    except Exception, e:
      log.otherError("status._statusDaemon", e)
    time.sleep(_reportingInterval)

def _loadConfig ():
  global _reportingInterval, _threadName
  _reportingInterval = int(config.config("DEFAULT.status_reporting_interval"))
  _threadName = uuid.uuid1().hex
  threading.Thread(target=_statusDaemon, name=_threadName).start()

_loadConfig()
config.addLoader(_loadConfig)
