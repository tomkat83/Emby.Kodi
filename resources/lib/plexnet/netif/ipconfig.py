# -*- coding: utf-8 -*-

import subprocess

def parse(data=None):
    data = data or subprocess.check_output('ipconfig /all',startupinfo=getStartupInfo())
    dlist = [d.rstrip() for d in data.split('\n')]
    mode = None
    sections = []
    while dlist:
        d = dlist.pop(0)
        try:
            if not d:
                continue
            elif not d.startswith(' '):
                sections.append({'name':d.strip('.: ')})
            elif d.startswith(' '):
                if d.endswith(':'):
                    k = d.strip(':. ')
                    mode = 'VALUE:' + k
                    sections[-1][k] = ''
                elif ':' in d:
                    k,v = d.split(':',1)
                    k = k.strip(':. ')
                    mode = 'VALUE:' + k
                    v = v.replace('(Preferred)','')
                    sections[-1][k] = v.strip()
            elif mode and mode.startswith('VALUE:'):
                if not d.startswith('        '):
                    mode = None
                    dlist.insert(0,d)
                    continue
                k = mode.split(':',1)[-1]
                v = d.replace('(Preferred)','')
                sections[-1][k] += ',' + v.strip()
        except:
            print d
            raise

    return sections[1:]

def getStartupInfo():
    if hasattr(subprocess,'STARTUPINFO'): #Windows
        startupinfo = subprocess.STARTUPINFO()
        try:
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW #Suppress terminal window
        except:
            startupinfo.dwFlags |= 1
        return startupinfo

    return None