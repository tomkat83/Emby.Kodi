import plexapp
import util


class Captions(object):
    def __init__(self):
        self.deviceInfo = plexapp.INTERFACE.getGlobal("deviceInfo")

        self.textSize = util.AttributeDict({
            'extrasmall': 15,
            'small': 20,
            'medium': 30,
            'large': 45,
            'extralarge': 65,
        })

        self.burnedSize = util.AttributeDict({
            'extrasmall': "60",
            'small': "80",
            'medium': "100",
            'large': "135",
            'extralarge': "200"
        })

        self.colors = util.AttributeDict({
            'white': 0xffffffff,
            'black': 0x000000ff,
            'red': 0xff0000ff,
            'green': 0x008000ff,
            'blue': 0x0000ffff,
            'yellow': 0xffff00ff,
            'magenta': 0xff00ffff,
            'cyan': 0x00ffffff,
        })

        self.defaults = util.AttributeDict({
            'textSize': self.textSize.medium,
            'textColor': self.colors.white,
            'textOpacity': 80,
            'backgroundColor': self.colors.black,
            'backgroundOpacity': 70,
            'burnedSize': None
        })

    def getTextSize(self):
        value = self.getOption("Text/Size")
        return self.textSize.get(value) or self.defaults.textSize

    def getTextColor(self):
        value = self.getOption("Text/Color")
        return self.colors.get(value) or self.defaults.textColor

    def getTextOpacity(self):
        value = self.getOption("Text/Opacity")
        if value is None or value == "default":
            return self.defaults.textOpacity
        else:
            return int(value)

    def getBackgroundColor(self):
        value = self.getOption("Background/Color")
        return self.colors.get(value) or self.defaults.backgroundColor

    def getBackgroundOpacity(self):
        value = self.getOption("Background/Opacity")
        if value is None or value == "default":
            return self.defaults.backgroundOpacity
        else:
            return int(value)

    def getBurnedSize(self):
        value = self.getOption("Text/Size")
        return self.burnedSize.get(value) or self.defaults.burnedSize

    def getOption(self, key):
        opt = self.deviceInfo.getCaptionsOption(key)
        return opt is not None and opt.lower().replace(' ', '') or None

CAPTIONS = Captions()
