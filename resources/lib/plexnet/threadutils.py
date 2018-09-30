# import inspect
# import ctypes
import threading
# import time


# def _async_raise(tid, exctype):
#     '''Raises an exception in the threads with id tid'''
#     if not inspect.isclass(exctype):
#         raise TypeError("Only types can be raised (not instances)")

#     try:
#         res = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(tid), ctypes.py_object(exctype))
#     except AttributeError:
#         # To catch: undefined symbol: PyThreadState_SetAsyncExc
#         return

#     if res == 0:
#         raise ValueError("invalid thread id")
#     elif res != 1:
#         # "if it returns a number greater than one, you're in trouble,
#         # and you should call it again with exc=NULL to revert the effect"
#         ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(tid), 0)
#         raise SystemError("PyThreadState_SetAsyncExc failed")


# class KillThreadException(Exception):
#     pass


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
