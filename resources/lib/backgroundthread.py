#!/usr/bin/env python
# -*- coding: utf-8 -*-

from logging import getLogger
import threading
import queue
import heapq
import xbmc

from . import utils, app

LOG = getLogger('PLEX.threads')


class KillableThread(threading.Thread):
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

    def __init__(self, group=None, target=None, name=None, args=(), kwargs={}):
        self._canceled = False
        # Set to True to set the thread to suspended
        self._suspended = False
        # Thread will return True only if suspended state is reached
        self.suspend_reached = False
        super(KillableThread, self).__init__(group, target, name, args, kwargs)

    def isCanceled(self):
        """
        Returns True if the thread is stopped
        """
        if self._canceled or xbmc.abortRequested:
            return True
        return False

    def abort(self):
        """
        Call to stop this thread
        """
        self._canceled = True

    def suspend(self, block=False):
        """
        Call to suspend this thread
        """
        self._suspended = True
        if block:
            while not self.suspend_reached:
                LOG.debug('Waiting for thread to suspend: %s', self)
                if app.APP.monitor.waitForAbort(0.1):
                    return

    def resume(self):
        """
        Call to revive a suspended thread back to life
        """
        self._suspended = False

    def wait_while_suspended(self):
        """
        Blocks until thread is not suspended anymore or the thread should
        exit.
        Returns True only if the thread should exit (=isCanceled())
        """
        while self.isSuspended():
            try:
                self.suspend_reached = True
                # Set in service.py
                if self.isCanceled():
                    # Abort was requested while waiting. We should exit
                    return True
                if app.APP.monitor.waitForAbort(0.1):
                    return True
            finally:
                self.suspend_reached = False
        return self.isCanceled()

    def isSuspended(self):
        """
        Returns True if the thread is suspended
        """
        return self._suspended


class OrderedQueue(queue.PriorityQueue, object):
    """
    Queue that enforces an order on the items it returns. An item you push
    onto the queue must be a tuple
        (index, item)
    where index=-1 is the item that will be returned first. The Queue will block
    until index=-1, 0, 1, 2, 3, ... is then made available
    """
    def __init__(self, maxsize=0):
        super(OrderedQueue, self).__init__(maxsize)
        self.smallest = -1
        self.not_next_item = threading.Condition(self.mutex)

    def _put(self, item, heappush=heapq.heappush):
        heappush(self.queue, item)
        if item[0] == self.smallest:
            self.not_next_item.notify()

    def get(self, block=True, timeout=None):
        """Remove and return an item from the queue.

        If optional args 'block' is true and 'timeout' is None (the default),
        block if necessary until an item is available. If 'timeout' is
        a non-negative number, it blocks at most 'timeout' seconds and raises
        the Empty exception if no item was available within that time.
        Otherwise ('block' is false), return an item if one is immediately
        available, else raise the Empty exception ('timeout' is ignored
        in that case).
        """
        self.not_empty.acquire()
        try:
            if not block:
                if not self._qsize() or self.queue[0][0] != self.smallest:
                    raise queue.Empty
            elif timeout is None:
                while not self._qsize():
                    self.not_empty.wait()
                while self.queue[0][0] != self.smallest:
                    self.not_next_item.wait()
            elif timeout < 0:
                raise ValueError("'timeout' must be a non-negative number")
            else:
                endtime = queue._time() + timeout
                while not self._qsize():
                    remaining = endtime - queue._time()
                    if remaining <= 0.0:
                        raise queue.Empty
                    self.not_empty.wait(remaining)
                while self.queue[0][0] != self.smallest:
                    remaining = endtime - queue._time()
                    if remaining <= 0.0:
                        raise queue.Empty
                    self.not_next_item.wait(remaining)
            item = self._get()
            self.smallest += 1
            self.not_full.notify()
            return item
        finally:
            self.not_empty.release()


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


class Task(object):
    def __init__(self, priority=None):
        self.priority = priority
        self._canceled = False
        self.finished = False

    def __cmp__(self, other):
        return self.priority - other.priority

    def start(self):
        BGThreader.addTask(self)

    def _run(self):
        self.run()
        self.finished = True

    def run(self):
        raise NotImplementedError

    def cancel(self):
        self._canceled = True

    def isCanceled(self):
        return self._canceled or xbmc.abortRequested

    def isValid(self):
        return not self.finished and not self._canceled


class FunctionAsTask(Task):
    def __init__(self, function, callback, *args, **kwargs):
        self._function = function
        self._callback = callback
        self._args = args
        self._kwargs = kwargs
        super(FunctionAsTask, self).__init__()

    def run(self):
        result = self._function(*self._args, **self._kwargs)
        if self._callback:
            self._callback(result)


class MutablePriorityQueue(queue.PriorityQueue):
    def _get(self, heappop=heapq.heappop):
            self.queue.sort()
            return heappop(self.queue)

    def lowest(self):
        """Return the lowest priority item in the queue (not reliable!)."""
        self.mutex.acquire()
        try:
            lowest = self.queue and min(self.queue) or None
        except Exception:
            lowest = None
            utils.ERROR()
        finally:
            self.mutex.release()
        return lowest


class BackgroundWorker(object):
    def __init__(self, queue, name=None):
        self._queue = queue
        self.name = name
        self._thread = None
        self._abort = False
        self._task = None

    @staticmethod
    def _runTask(task):
        if task._canceled:
            return
        try:
            task._run()
        except Exception:
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
        except queue.Empty:
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


class NonstoppingBackgroundWorker(BackgroundWorker):
    def __init__(self, queue, name=None):
        self._working = False
        super(NonstoppingBackgroundWorker, self).__init__(queue, name)

    def _queueLoop(self):
        while not self.aborted():
            try:
                self._task = self._queue.get_nowait()
                self._working = True
                self._runTask(self._task)
                self._working = False
                self._queue.task_done()
                self._task = None
            except queue.Empty:
                app.APP.monitor.waitForAbort(0.05)

    def working(self):
        return self._working


class BackgroundThreader:
    def __init__(self, name=None, worker=BackgroundWorker, worker_count=6):
        self.name = name
        self._queue = MutablePriorityQueue()
        self._abort = False
        self.priority = -1
        self.workers = [worker(self._queue, 'queue.{0}:worker.{1}'.format(self.name, x)) for x in range(worker_count)]

    def _nextPriority(self):
        self.priority += 1
        return self.priority

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
        task.priority = self._nextPriority()
        self._queue.put(task)
        self.startWorkers()

    def addTasks(self, tasks):
        for t in tasks:
            t.priority = self._nextPriority()
            self._queue.put(t)

        self.startWorkers()

    def addTasksToFront(self, tasks):
        lowest = self.getLowestPrority()
        if lowest is None:
            return self.addTasks(tasks)

        p = lowest - len(tasks)
        for t in tasks:
            t.priority = p
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

        return lowest.priority

    def moveToFront(self, qitem):
        lowest = self.getLowestPrority()
        if lowest is None:
            return

        qitem.priority = lowest - 1


class ThreaderManager:
    def __init__(self, worker=BackgroundWorker, worker_count=6):
        self.index = 0
        self.abandoned = []
        self._workerhandler = worker
        self.threader = BackgroundThreader(name=str(self.index),
                                           worker=worker,
                                           worker_count=worker_count)

    def __getattr__(self, name):
        return getattr(self.threader, name)

    def reset(self):
        if self.threader._queue.empty() and not self.threader.hasTask():
            return

        self.index += 1
        self.abandoned.append(self.threader.abort())
        self.threader = BackgroundThreader(name=str(self.index),
                                           worker=self._workerhandler)

    def shutdown(self):
        self.threader.shutdown()
        for a in self.abandoned:
            a.shutdown()


BGThreader = ThreaderManager()
