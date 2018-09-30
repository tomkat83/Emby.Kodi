import random

import plexobjects
import signalsmixin


class BasePlaylist(plexobjects.PlexObject, signalsmixin.SignalsMixin):
    TYPE = 'baseplaylist'

    isRemote = False

    def __init__(self, *args, **kwargs):
        plexobjects.PlexObject.__init__(self, *args, **kwargs)
        signalsmixin.SignalsMixin.__init__(self)
        self._items = []
        self._shuffle = None
        self.pos = 0
        self.startShuffled = False
        self.isRepeat = False
        self.isRepeatOne = False

    def __getitem__(self, idx):
        if self._shuffle:
            return self._items[self._shuffle[idx]]
        else:
            return self._items[idx]

    def __iter__(self):
        if self._shuffle:
            for i in self._shuffle:
                yield self._items[i]
        else:
            for i in self._items:
                yield i

    def __len__(self):
        return len(self._items)

    def items(self):
        if self._shuffle:
            return [i for i in self]
        else:
            return self._items

    def setRepeat(self, repeat, one=False):
        if self.isRepeat == repeat and self.isRepeatOne == one:
            return

        self.isRepeat = repeat
        self.isRepeatOne = one

    def hasNext(self):
        if len(self._items) < 2:
            return False
        if self.isRepeatOne:
            return False
        if self.isRepeat:
            return True
        return self.pos < len(self._items) - 1

    def hasPrev(self):
        if len(self._items) < 2:
            return False
        if self.isRepeatOne:
            return False
        if self.isRepeat:
            return True
        return self.pos > 0

    def next(self):
        if not self.hasNext():
            return False

        if self.isRepeatOne:
            return True

        self.pos += 1
        if self.pos >= len(self._items):
            self.pos = 0

        return True

    def prev(self):
        if not self.hasPrev():
            return False

        if self.isRepeatOne:
            return True

        self.pos -= 1
        if self.pos < 0:
            self.pos = len(self._items) - 1

        return True

    def getPosFromItem(self, item):
        if item not in self._items:
            return -1
        return self._items.index(item)

    def setCurrent(self, pos):
        if not isinstance(pos, int):
            item = pos
            pos = self.getPosFromItem(item)
            self._items[pos] = item

        if pos < 0 or pos >= len(self._items):
            return False

        self.pos = pos
        return True

    def current(self):
        return self[self.pos]

    def userCurrent(self):
        for item in self._items:
            if not item.isWatched or item.viewOffset.asInt():
                return item
        else:
            return self.current()

    def prevItem(self):
        if self.pos < 1:
            return None
        return self[self.pos - 1]

    def shuffle(self, on=True, first=False):
        if on and self._items:
            self._shuffle = range(len(self._items))
            random.shuffle(self._shuffle)
            if not first:
                self.pos = self._shuffle.index(self.pos)
        else:
            if self._shuffle:
                self.pos = self._shuffle[self.pos]
            if not first:
                self._shuffle = None
        self.trigger('items.changed')
        self.refresh()

    def setShuffle(self, shuffle=None):
        if shuffle is None:
            shuffle = not self.isShuffled

        self.shuffle(shuffle)

    @property
    def isShuffled(self):
        return bool(self._shuffle)

    def refresh(self, *args, **kwargs):
        self.trigger('change')


class LocalPlaylist(BasePlaylist):
    TYPE = 'localplaylist'

    def __init__(self, items, server, media_item=None):
        BasePlaylist.__init__(self, None, server=server)
        self._items = items
        self._mediaItem = media_item

    def __getattr__(self, name):
        if not self._mediaItem:
            return BasePlaylist.__getattr__(self, name)
        return getattr(self._mediaItem, name)

    def get(self, name, default=''):
        if not self._mediaItem:
            return BasePlaylist.get(self, name, default)

        return self._mediaItem.get(name, default)

    @property
    def defaultArt(self):
        if not self._mediaItem:
            return super(LocalPlaylist, self).defaultArt
        return self._mediaItem.defaultArt
