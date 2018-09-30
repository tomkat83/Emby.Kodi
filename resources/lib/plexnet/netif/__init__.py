import socket
import struct

class Interface:
    def __init__(self):
        self.name = ''
        self.ip = ''
        self.mask = ''

    @property
    def broadcast(self):
        if self.name == 'FALLBACK': return '<broadcast>'
        if not self.ip or not self.mask: return None
        return calcBroadcast(self.ip,self.mask)

def getInterfaces():
    try:
        return _getInterfaces()
    except:
        pass

    try:
        return _getInterfacesBSD()
    except:
        pass

    try:
        return _getInterfacesWin()
    except:
        pass

    i = Interface()
    i.name = 'FALLBACK'
    return [i]

def _getInterfaces():
    vals = all_interfaces()
    interfaces = []
    for name,ip in vals:
        i = Interface()
        i.name = name
        i.ip = ip
        try:
            mask = getSubnetMask(i.name)
            i.mask = mask
        except:
            i.mask = ''
        interfaces.append(i)
    return interfaces

def _getInterfacesBSD():
    #name flags family address netmask
    interfaces = []
    import getifaddrs
    for info in getifaddrs.getifaddrs():
        if info.family == 2:
            i = Interface()
            i.name = info.name
            i.ip = info.address
            i.mask = info.netmask
            interfaces.append(i)
    return interfaces

def _getInterfacesWin():
    import ipconfig
    interfaces = []
    adapters = ipconfig.parse()
    for a in adapters:
        if not 'IPv4 Address' in a: continue
        if not 'Subnet Mask' in a: continue
        i = Interface()
        i.name = a.get('name','UNKNOWN')
        i.ip = a['IPv4 Address']
        i.mask = a['Subnet Mask']
        interfaces.append(i)
    return interfaces

def all_interfaces():
    import sys
    import array
    import fcntl

    is_64bits = sys.maxsize > 2**32
    struct_size = 40 if is_64bits else 32
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    max_possible = 8 # initial value
    while True:
        bytes = max_possible * struct_size
        names = array.array('B', '\0' * bytes)
        outbytes = struct.unpack('iL', fcntl.ioctl(
            s.fileno(),
            0x8912,  # SIOCGIFCONF
            struct.pack('iL', bytes, names.buffer_info()[0])
        ))[0]
        if outbytes == bytes:
            max_possible *= 2
        else:
            break
    namestr = names.tostring()
    return [(namestr[i:i+16].split('\0', 1)[0],
             socket.inet_ntoa(namestr[i+20:i+24]))
            for i in range(0, outbytes, struct_size)]

def getSubnetMask(name):
    import fcntl
    return socket.inet_ntoa(fcntl.ioctl(socket.socket(socket.AF_INET, socket.SOCK_DGRAM), 35099, struct.pack('256s', name))[20:24])

def calcIPValue(ipaddr):
        """
        Calculates the binary
        value of the ip addresse
        """
        ipaddr = ipaddr.split('.')
        value = 0
        for i in range(len(ipaddr)):
                value = value | (int(ipaddr[i]) << ( 8*(3-i) ))
        return value

def calcIPNotation(value):
        """
        Calculates the notation
        of the ip addresse given its value
        """
        notat = []
        for i in range(4):
                shift = 255 << ( 8*(3-i) )
                part = value & shift
                part = part >> ( 8*(3-i) )
                notat.append(str(part))
        notat = '.'.join(notat)
        return notat

def calcSubnet(cidr):
        """
        Calculates the Subnet
        based on the CIDR
        """
        subn = 4294967295 << (32-cidr)  # 4294967295 = all bits set to 1
        subn = subn % 4294967296        # round it back to be 4 bytes
        subn = calcIPNotation(subn)
        return subn

def calcCIDR(subnet):
        """
        Calculates the CIDR
        based on the SUbnet
        """
        cidr = 0
        subnet = calcIPValue(subnet)
        while subnet != 0:
                subnet = subnet << 1
                subnet = subnet % 4294967296
                cidr += 1
        return cidr

def calcNetpart(ipaddr,subnet):
        ipaddr = calcIPValue(ipaddr)
        subnet = calcIPValue(subnet)
        netpart = ipaddr & subnet
        netpart = calcIPNotation(netpart)
        return netpart

def calcMacpart(subnet):
        macpart = ~calcIPValue(subnet)
        macpart = calcIPNotation(macpart)
        return macpart

def calcBroadcast(ipaddr,subnet):
        netpart = calcNetpart(ipaddr,subnet)
        macpart = calcMacpart(subnet)
        netpart = calcIPValue(netpart)
        macpart = calcIPValue(macpart)
        broadcast = netpart | macpart
        broadcast = calcIPNotation(broadcast)
        return broadcast

def calcDefaultGate(ipaddr,subnet):
        defaultgw = calcNetpart(ipaddr,subnet)
        defaultgw = calcIPValue(defaultgw) + 1
        defaultgw = calcIPNotation(defaultgw)
        return defaultgw

def calcHostNum(subnet):
        macpart = calcMacpart(subnet)
        hostnum = calcIPValue(macpart) - 1
        return hostnum