#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
from time import time as _time
import threading
import queue
import heapq
from collections import deque
from functools import total_ordering

from . import utils, app, variables as v

WORKER_COUNT = 3
LOG = getLogger('PLEX.threads')


class KillableThread(threading.Thread):
    def __init__(self, group=None, target=None, name=None, args=(), kwargs={}):
        self._canceled = False
        self._suspended = False
        self._is_not_suspended = threading.Event()
        self._is_not_suspended.set()
        self._suspension_reached = threading.Event()
        self._is_not_asleep = threading.Event()
        self._is_not_asleep.set()
        self.suspension_timeout = None
        super(KillableThread, self).__init__(group, target, name, args, kwargs)

    def should_cancel(self):
        """
        Returns True if the thread should be stopped immediately
        """
        return self._canceled or app.APP.stop_pkc

    def cancel(self):
        """
        Call from another thread to stop this current thread
        """
        self._canceled = True
        # Make sure thread is running in order to exit quickly
        self._is_not_asleep.set()
        self._is_not_suspended.set()

    def should_suspend(self):
        """
        Returns True if the current thread should be suspended immediately
        """
        return self._suspended

    def suspend(self, block=False, timeout=None):
        """
        Call from another thread to suspend the current thread. Provide a
        timeout [float] in seconds optionally. block=True will block the caller
        until the thread-to-be-suspended is indeed suspended
        Will wake a thread that is asleep!
        """
        self.suspension_timeout = timeout
        self._suspended = True
        self._is_not_suspended.clear()
        # Make sure thread wakes up in order to suspend
        self._is_not_asleep.set()
        if block:
            self._suspension_reached.wait()

    def resume(self):
        """
        Call from another thread to revive a suspended or asleep current thread
        back to life
        """
        self._suspended = False
        self._is_not_asleep.set()
        self._is_not_suspended.set()

    def wait_while_suspended(self):
        """
        Blocks until thread is not suspended anymore or the thread should
        exit or for a period of self.suspension_timeout (set by the caller of
        suspend())
        Returns the value of should_cancel()
        """
        self._suspension_reached.set()
        self._is_not_suspended.wait(self.suspension_timeout)
        self._suspension_reached.clear()
        return self.should_cancel()

    def is_suspended(self):
        """
        Check from another thread whether the current thread is suspended
        """
        return self._suspension_reached.is_set()

    def sleep(self, timeout):
        """
        Only call from the current thread in order to sleep for a period of
        timeout [float, seconds]. Will unblock immediately if thread should
        cancel (should_cancel()) or the thread should_suspend
        """
        self._is_not_asleep.clear()
        self._is_not_asleep.wait(timeout)
        self._is_not_asleep.set()

    def is_asleep(self):
        """
        Check from another thread whether the current thread is asleep
        """
        return not self._is_not_asleep.is_set()

    def unblock_callers(self):
        """
        Ensures that any other thread that requested this thread's suspension
        is released
        """
        self._suspension_reached.set()


class ProcessingQueue(queue.Queue, object):
    """
    Queue of queues that processes a queue completely before moving on to the
    next queue. There's one queue per Section(). You need to initialize each
    section with add_section(section) first.
    Put tuples (count, item) into this queue, with count being the respective
    position of the item in the queue, starting with 0 (zero).
    (None, None) is the sentinel for a single queue being exhausted, added by
    add_sentinel()
    """
    def _init(self, maxsize):
        self.queue = deque()
        self._sections = deque()
        self._queues = deque()
        self._current_section = None
        self._current_queue = None
        # Item-index for the currently active queue
        self._counter = 0

    def _qsize(self):
        return self._current_queue._qsize() if self._current_queue else 0

    def _put(self, item):
        for i, section in enumerate(self._sections):
            if item[1]['section'] == section:
                self._queues[i]._put(item)
                break
        else:
            raise RuntimeError('Could not find section for item %s' % item[1])

    def add_sentinel(self, section):
        """
        Adds a new empty section as a sentinel. Call with an empty Section()
        object. Call this method immediately after having added all sections
        with add_section().
        Once the get()-method returns None, you've received the sentinel and
        you've thus exhausted the queue
        """
        with self.not_full:
            section.number_of_items = 1
            self._add_section(section)
            # Add the actual sentinel to the queue we just added
            self._queues[-1]._put((None, None))
            self.unfinished_tasks += 1
            self.not_empty.notify()

    def add_section(self, section):
        """
        Add a new Section() to this Queue. Each section will be entirely
        processed before moving on to the next section.

        Be sure to set section.number_of_items correctly as it will signal
        when processing is completely done for a specific section!
        """
        with self.mutex:
            self._add_section(section)

    def change_section_number_of_items(self, section, number_of_items):
        """
        Hit this method if you've reset section.number_of_items to make
        sure we're not blocking
        """
        with self.mutex:
            self._change_section_number_of_items(section, number_of_items)

    def _change_section_number_of_items(self, section, number_of_items):
        section.number_of_items = number_of_items
        if (self._current_section == section
                and self._counter == number_of_items):
            # We were actually waiting for more items to come in - but there
            # aren't any!
            self._init_next_section()
            if self._qsize() > 0:
                self.not_empty.notify()

    def _add_section(self, section):
        self._sections.append(section)
        self._queues.append(
            OrderedQueue() if section.plex_type == v.PLEX_TYPE_ALBUM
            else queue.Queue())
        if self._current_section is None:
            self._activate_next_section()

    def _init_next_section(self):
        """
        Call only when a section has been completely exhausted
        """
        self._sections.popleft()
        self._queues.popleft()
        self._activate_next_section()

    def _activate_next_section(self):
        self._counter = 0
        self._current_section = self._sections[0] if self._sections else None
        self._current_queue = self._queues[0] if self._queues else None

    def _get(self):
        item = self._current_queue._get()
        self._counter += 1
        if self._counter == self._current_section.number_of_items:
            self._init_next_section()
        return item[1]


class OrderedQueue(queue.PriorityQueue, object):
    """
    Queue that enforces an order on the items it returns. An item you push
    onto the queue must be a tuple
        (index, item)
    where index=-1 is the item that will be returned first. The Queue will block
    until index=-1, 0, 1, 2, 3, ... is then made available

    maxsize will be rather fuzzy, as _qsize returns 0 if we're still waiting
    for the next smalles index. put() thus might not block always when it
    should.
    """
    def __init__(self, maxsize=0):
        self.next_index = 0
        super(OrderedQueue, self).__init__(maxsize)

    def _qsize(self):
        try:
            return len(self.queue) if self.queue[0][0] == self.next_index else 0
        except IndexError:
            return 0

    def _get(self):
        self.next_index += 1
        return heapq.heappop(self.queue)


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


@total_ordering
class Task(object):
    def __init__(self, priority=None):
        self.priority = priority
        self._canceled = False
        self.finished = False

    def __lt__(self, other):
        """Magic method Task<Other Task; compares the tasks' priorities."""
        return self.priority - other.priority > 0

    def __eq__(self, other):
        """Magic method Task=Other Task; compares the tasks' priorities."""
        return self.priority == other.priority

    def start(self):
        BGThreader.addTask(self)

    def _run(self):
        self.run()
        self.finished = True

    def run(self):
        raise NotImplementedError

    def cancel(self):
        self._canceled = True

    def should_cancel(self):
        return self._canceled or app.APP.monitor.abortRequested()

    def isValid(self):
        return not self.finished and not self._canceled


class ShutdownSentinel(Task):
    def run(self):
        pass


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
    def _get(self):
            self.queue.sort()
            return heapq.heappop(self.queue)

    def lowest(self):
        """Return the lowest priority item in the queue (not reliable!)."""
        self.mutex.acquire()
        try:
            lowest = self.queue and min(self.queue) or None
        except Exception:
            lowest = None
            utils.ERROR(notify=True)
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
            utils.ERROR(notify=True)

    def abort(self):
        self._abort = True
        return self

    def aborted(self):
        return self._abort or app.APP.monitor.abortRequested()

    def start(self):
        if self._thread and self._thread.is_alive():
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

    def shutdown(self, block=True):
        self.abort()

        if self._task:
            self._task.cancel()

        if block and self._thread and self._thread.is_alive():
            LOG.debug('thread (%s): Waiting...', self.name)
            self._thread.join()
            LOG.debug('thread (%s): Done', self.name)

    def working(self):
        return self._thread and self._thread.is_alive()


class NonstoppingBackgroundWorker(BackgroundWorker):
    def __init__(self, queue, name=None):
        self._working = False
        super(NonstoppingBackgroundWorker, self).__init__(queue, name)

    def _queueLoop(self):
        LOG.debug('Starting Worker %s', self.name)
        while not self.aborted():
            self._task = self._queue.get()
            if self._task is ShutdownSentinel:
                break
            self._working = True
            self._runTask(self._task)
            self._working = False
            self._queue.task_done()
            self._task = None
        LOG.debug('Exiting Worker %s', self.name)

    def working(self):
        return self._working


class BackgroundThreader(object):
    def __init__(self, name=None, worker=BackgroundWorker, worker_count=6):
        self.name = name
        self._queue = MutablePriorityQueue()
        self._abort = False
        self.priority = -1
        self.workers = [
            worker(self._queue, 'queue.{0}:worker.{1}'.format(self.name, x))
            for x in range(worker_count)
        ]

    def _nextPriority(self):
        self.priority += 1
        return self.priority

    def abort(self):
        self._abort = True
        for w in self.workers:
            w.abort()
        return self

    def aborted(self):
        return self._abort or app.APP.monitor.abortRequested()

    def shutdown(self, block=True):
        self.abort()
        self.addTasksToFront([ShutdownSentinel() for _ in self.workers])
        for w in self.workers:
            w.shutdown(block)

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


class ThreaderManager(object):
    def __init__(self,
                 worker=NonstoppingBackgroundWorker,
                 worker_count=WORKER_COUNT):
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

    def shutdown(self, block=True):
        self.threader.shutdown(block)
        for a in self.abandoned:
            a.shutdown(block)


BGThreader = ThreaderManager()
