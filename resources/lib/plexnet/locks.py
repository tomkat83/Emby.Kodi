# Generic Locks. These are only virtual. You will need to check for the lock to
# ignore processing depending on the lockName.
#  * Locks().Lock("lockName")      : creates virtual lock
#  * Locks().IsLocked("lockName")  : returns true if locked
#  * Locks().Unlock("lockName")    : return true if existed & removed
import util


class Locks(object):
    def __init__(self):
        self.locks = {}
        self.oneTimeLocks = {}

    def lock(self, name):
        self.locks[name] = (self.locks.get(name) or 0) + 1
        util.DEBUG_LOG("Lock {0}, total={0}".format(name, self.locks[name]))

    def lockOnce(self, name):
        util.DEBUG_LOG("Locking once {0}".format(name))
        self.oneTimeLocks[name] = True

    def unlock(self, name, forceUnlock=False):
        oneTime = False
        if name in self.oneTimeLocks:
            del self.oneTimeLocks[name]
            oneTime = True
        normal = (self.locks.get(name) or 0) > 0

        if normal:
            if forceUnlock:
                self.locks[name] = 0
            else:
                self.locks[name] -= 1

            if self.locks[name] <= 0:
                del self.locks[name]
            else:
                normal = False

        unlocked = (normal or oneTime)
        util.DEBUG_LOG("Unlock {0}, total={1}, unlocked={2}".format(name, self.locks.get(name) or 0, unlocked))

        return unlocked

    def isLocked(self, name):
        return name in self.oneTimeLocks or name in self.locks
        # return (self.oneTimeLocks.Delete(name) or self.locks.DoesExist(name))


# lock helpers
def disableBackButton():
    LOCKS.lock("BackButton")


def enableBackButton():
    LOCKS.unlock("BackButton", True)


def disableRemoteControl():
    LOCKS.lock("roUniversalControlEvent")


def enableRemoteControl():
    LOCKS.unlock("roUniversalControlEvent", True)

LOCKS = Locks()
