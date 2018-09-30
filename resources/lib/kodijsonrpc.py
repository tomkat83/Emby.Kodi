import xbmc
import json


class JSONRPCMethod:

    class Exception(Exception):
        pass

    def __init__(self):
        self.family = None

    def __getattr__(self, method):
        def handler(**kwargs):
            command = {
                'jsonrpc': '2.0',
                'id': 1,
                'method': '{0}.{1}'.format(self.family, method)
            }

            if kwargs:
                command['params'] = kwargs

            # xbmc.log(json.dumps(command))
            ret = json.loads(xbmc.executeJSONRPC(json.dumps(command)))

            if ret:
                if 'error' in ret:
                    raise self.Exception(ret['error'])
                else:
                    return ret['result']
            else:
                return None

        return handler

    def __call__(self, family):
        self.family = family
        return self


class KodiJSONRPC:
    def __init__(self):
        self.methodHandler = JSONRPCMethod()

    def __getattr__(self, family):
        return self.methodHandler(family)


rpc = KodiJSONRPC()


class BuiltInMethod:

    class Exception(Exception):
        pass

    def __init__(self):
        self.module = None

    def __getattr__(self, method):
        def handler(*args, **kwargs):
            args = [str(a).replace(',', '\,') for a in args]
            for k, v in kwargs.items():
                args.append('{0}={v}'.format(k, str(v).replace(',', '\,')))

            if args:
                command = '{0}.{1}({2})'.format(self.module, method, ','.join(args))
            else:
                command = '{0}.{1}'.format(self.module, method)

            xbmc.log(command, xbmc.LOGNOTICE)

            xbmc.executebuiltin(command)

        return handler

    def __call__(self, *args, **kwargs):
        args = [str(a).replace(',', '\,') for a in args]
        for k, v in kwargs.items():
            args.append('{0}={v}'.format(k, str(v).replace(',', '\,')))

        if args:
            command = '{0}({1})'.format(self.module, ','.join(args))
        else:
            command = '{0}'.format(self.module)

        xbmc.log(command, xbmc.LOGNOTICE)

        xbmc.executebuiltin(command)

    def initModule(self, module):
        self.module = module
        return self


class KodiBuiltin:
    def __init__(self):
        self.methodHandler = BuiltInMethod()

    def __getattr__(self, module):
        return self.methodHandler.initModule(module)


builtin = KodiBuiltin()
