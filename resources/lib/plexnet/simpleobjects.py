class Res(tuple):
    def __str__(self):
        return '{0}x{1}'.format(*self[:2])

    @classmethod
    def fromString(cls, res_string):
        try:
            return cls(map(lambda n: int(n), res_string.split('x')))
        except:
            return None


class AttributeDict(dict):
    def __getattr__(self, attr):
        return self.get(attr)

    def __setattr__(self, attr, value):
        self[attr] = value

    def __repr__(self):
        return '<{0}:{1}:{2}>'.format(self.__class__.__name__, self.id, self.get('title', 'None').encode('utf8'))
