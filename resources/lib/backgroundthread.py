#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
import threading
import Queue
import heapq
import xbmc

from . import utils

LOG = getLogger('PLEX.' + __name__)


class KillableThread(threading.Thread):
    pass
    '''A thread class that supports raising exception in the thread from
       another thread.
    '''
    # def _get_my_tid(self):
    #     """determines this (self's) thread id

    #     CAREFUL : this function is executed in the context of the caller
    #     thread, to get the identity of the thread represented by this
    #     instance.
    #     """
    #     if not self.isAlive():
    #         raise threading.ThreadError("the thread is not active")

    #     return self.ident

    # def _raiseExc(self, exctype):
    #     """Raises the given exception type in the context of this thread.

    #     If the thread is busy in a system call (time.sleep(),
    #     socket.accept(), ...), the exception is simply ignored.

    #     If you are sure that your exception should terminate the thread,
    #     one way to ensure that it works is:

    #         t = ThreadWithExc( ... )
    #         ...
    #         t.raiseExc( SomeException )
    #         while t.isAlive():
    #             time.sleep( 0.1 )
    #             t.raiseExc( SomeException )

    #     If the exception is to be caught by the thread, you need a way to
    #     check that your thread has caught it.

    #     CAREFUL : this function is executed in the context of the
    #     caller thread, to raise an excpetion in the context of the
    #     thread represented by this instance.
    #     """
    #     _async_raise(self._get_my_tid(), exctype)

    def kill(self, force_and_wait=False):
        pass
    #     try:
    #         self._raiseExc(KillThreadException)

    #         if force_and_wait:
    #             time.sleep(0.1)
    #             while self.isAlive():
    #                 self._raiseExc(KillThreadException)
    #                 time.sleep(0.1)
    #     except threading.ThreadError:
    #         pass

    # def onKilled(self):
    #     pass

    # def run(self):
    #     try:
    #         self._Thread__target(*self._Thread__args, **self._Thread__kwargs)
    #     except KillThreadException:
    #         self.onKilled()


class Tasks(list):
    def add(self, task):
        for t in self:
            if not t.isValid():
                self.remove(t)

        if isinstance(task, list):
            self += task
        else:
            self.append(task)

    def cancel(self):
        while self:
            self.pop().cancel()


class Task:
    def __init__(self, priority=None):
        self._priority = priority
        self._canceled = False
        self.finished = False

    def __cmp__(self, other):
        return self._priority - other._priority

    def start(self):
        BGThreader.addTask(self)

    def _run(self):
        self.run()
        self.finished = True

    def run(self):
        pass

    def cancel(self):
        self._canceled = True

    def isCanceled(self):
        return self._canceled or xbmc.abortRequested

    def isValid(self):
        return not self.finished and not self._canceled


class MutablePriorityQueue(Queue.PriorityQueue):
    def _get(self, heappop=heapq.heappop):
            self.queue.sort()
            return heappop(self.queue)

    def lowest(self):
        """Return the lowest priority item in the queue (not reliable!)."""
        self.mutex.acquire()
        try:
            lowest = self.queue and min(self.queue) or None
        except:
            lowest = None
            utils.ERROR()
        finally:
            self.mutex.release()
        return lowest


class BackgroundWorker:
    def __init__(self, queue, name=None):
        self._queue = queue
        self.name = name
        self._thread = None
        self._abort = False
        self._task = None

    def _runTask(self, task):
        if task._canceled:
            return
        try:
            task._run()
        except:
            utils.ERROR()

    def abort(self):
        self._abort = True
        return self

    def aborted(self):
        return self._abort or xbmc.abortRequested

    def start(self):
        if self._thread and self._thread.isAlive():
            return

        self._thread = KillableThread(target=self._queueLoop, name='BACKGROUND-WORKER({0})'.format(self.name))
        self._thread.start()

    def _queueLoop(self):
        if self._queue.empty():
            return

        LOG.debug('(%s): Active', self.name)
        try:
            while not self.aborted():
                self._task = self._queue.get_nowait()
                self._runTask(self._task)
                self._queue.task_done()
                self._task = None
        except Queue.Empty:
            LOG.debug('(%s): Idle', self.name)

    def shutdown(self):
        self.abort()

        if self._task:
            self._task.cancel()

        if self._thread and self._thread.isAlive():
            LOG.debug('thread (%s): Waiting...', self.name)
            self._thread.join()
            LOG.debug('thread (%s): Done', self.name)

    def working(self):
        return self._thread and self._thread.isAlive()


class BackgroundThreader:
    def __init__(self, name=None, worker_count=8):
        self.name = name
        self._queue = MutablePriorityQueue()
        self._abort = False
        self._priority = -1
        self.workers = [BackgroundWorker(self._queue, 'queue.{0}:worker.{1}'.format(self.name, x)) for x in range(worker_count)]

    def _nextPriority(self):
        self._priority += 1
        return self._priority

    def abort(self):
        self._abort = True
        for w in self.workers:
            w.abort()
        return self

    def aborted(self):
        return self._abort or xbmc.abortRequested

    def shutdown(self):
        self.abort()

        for w in self.workers:
            w.shutdown()

    def addTask(self, task):
        task._priority = self._nextPriority()
        self._queue.put(task)
        self.startWorkers()

    def addTasks(self, tasks):
        for t in tasks:
            t._priority = self._nextPriority()
            self._queue.put(t)

        self.startWorkers()

    def addTasksToFront(self, tasks):
        lowest = self.getLowestPrority()
        if lowest is None:
            return self.addTasks(tasks)

        p = lowest - len(tasks)
        for t in tasks:
            t._priority = p
            self._queue.put(t)
            p += 1

        self.startWorkers()

    def startWorkers(self):
        for w in self.workers:
            w.start()

    def working(self):
        return not self._queue.empty() or self.hasTask()

    def hasTask(self):
        return any([w.working() for w in self.workers])

    def getLowestPrority(self):
        lowest = self._queue.lowest()
        if not lowest:
            return None

        return lowest._priority

    def moveToFront(self, qitem):
        lowest = self.getLowestPrority()
        if lowest is None:
            return

        qitem._priority = lowest - 1


class ThreaderManager:
    def __init__(self):
        self.index = 0
        self.abandoned = []
        self.threader = BackgroundThreader(str(self.index))

    def __getattr__(self, name):
        return getattr(self.threader, name)

    def reset(self):
        if self.threader._queue.empty() and not self.threader.hasTask():
            return

        self.index += 1
        self.abandoned.append(self.threader.abort())
        self.threader = BackgroundThreader(str(self.index))

    def shutdown(self):
        self.threader.shutdown()
        for a in self.abandoned:
            a.shutdown()


BGThreader = ThreaderManager()
