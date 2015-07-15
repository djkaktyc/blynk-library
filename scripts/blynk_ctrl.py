#!/usr/bin/python
'''
examples:

  Simple operations:  
    python blynk_ctrl.py --token=909fa1...1a9774 -dw 5 1
    python blynk_ctrl.py --token=909fa1...1a9774 -aw 9 134
    python blynk_ctrl.py --token=909fa1...1a9774 -vw 1 value

  Using named pins (like A1, supported by some boards):
    python blynk_ctrl.py --token=909fa1...1a9774 -dw A1 1

  Multiple operations at once:
    python blynk_ctrl.py --token=909fa1...1a9774 -aw 9 100 -dw 8 123 -vw 9 hello

  Sending arrays to virtual pins:
    python blynk_ctrl.py --token=909fa1...1a9774 -vw 1 "value 1" "value 2"

note:
  Read is not supported yet

 Author:   Volodymyr Shymanskyy
 License:  The MIT license
'''
import socket, struct
import sys, time
import argparse
import logging

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawTextHelpFormatter,
    description = 'This script uses Bridge feature to control another device from the command line.',
    epilog = __doc__
)

import copy

def opAction(op):
    class _action(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            if getattr(namespace, self.dest, None) is None:
                setattr(namespace, self.dest, [])
            items = copy.copy(getattr(namespace, self.dest))
            items.append([op]+values)
            setattr(namespace, self.dest, items)
            
    return _action

parser.add_argument('-t', '--token',  action="store",      dest='token',            help='auth token of the controller')

parser.add_argument('-dw', '--digitalWrite', action=opAction('dw'), dest='ops', nargs=2,   metavar=('PIN', 'VAL'), default=[])
parser.add_argument('-aw', '--analogWrite',  action=opAction('aw'), dest='ops', nargs=2,   metavar=('PIN', 'VAL'), default=[])
parser.add_argument('-vw', '--virtualWrite', action=opAction('vw'), dest='ops', nargs='*', metavar=('PIN', 'VAL'), default=[])

parser.add_argument('-dr', '--digitalRead',  action=opAction('dr'), dest='ops', nargs=1,   metavar='PIN', default=[])
parser.add_argument('-ar', '--analogRead',   action=opAction('ar'), dest='ops', nargs=1,   metavar='PIN', default=[])
parser.add_argument('-vr', '--virtualRead',  action=opAction('vr'), dest='ops', nargs=1,   metavar='PIN', default=[])

parser.add_argument('-s', '--server', action='store',      dest='server',           help='server address or domain name')
parser.add_argument('-p', '--port',   action="store",      dest='port',   type=int, help='server port')
parser.add_argument('--target',       action="store",      dest='target', metavar="TOKEN", help='auth token of the target device')
parser.add_argument('--dump',         action="store_true", dest='dump',             help='dump communication')

parser.set_defaults(
    server='cloud.blynk.cc',
    port=8442,
    dump=False,
    nodelay=True,
    bridge=64
)

args = parser.parse_args()

#import pprint
#pprint.pprint(args)
#sys.exit()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("blynk_ctrl")

if not args.target and args.token:
    args.target = args.token

if not args.token:
    parser.error("token not specified!")
    
if args.dump:
    log.setLevel(logging.DEBUG)

# Helpers

hdr = struct.Struct("!BHH")

class MsgType:
    RSP    = 0
    LOGIN  = 2
    PING   = 6
    BRIDGE = 15
    HW     = 20

class MsgStatus:
    OK     = 200

def compose(msg_type, *args):
    # Convert params to string and join using \0
    data = "\0".join(map(str, args))
    msg_id = genMsgId()
    msg_len = len(data)
    log.debug("< %2d,%2d,%2d : %s", msg_type, msg_id, msg_len, "=".join(map(str, args)))
    return hdr.pack(msg_type, msg_id, msg_len) + data

static_msg_id = 1
def genMsgId():
    global static_msg_id
    static_msg_id += 1
    return static_msg_id

def receive(sock, length):
    d = []
    l = 0
    while l < length:
        r = ''
        try:
            r = sock.recv(length-l)
        except socket.timeout:
            continue
        if not r:
            return ''
        d.append(r)
        l += len(r)
    return ''.join(d)

# Main code
try:
    conn = socket.create_connection((args.server, args.port), 3)
except:
    log.error("Can't connect to %s:%d", args.server, args.port)
    sys.exit(1)

if args.nodelay:
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    
# Authenticate
conn.sendall(compose(MsgType.LOGIN, args.token))
data = receive(conn, hdr.size)
if not data:
    log.error("Login timeout")
    sys.exit(1)

msg_type, msg_id, msg_status = hdr.unpack(data)
if msg_type != MsgType.RSP or msg_status != MsgStatus.OK:
    log.error("Login failed: %d,%d,%d", msg_type, msg_id, msg_status)
    sys.exit(1)

conn.sendall(compose(MsgType.BRIDGE, args.bridge, "i", args.target))

def do_read(cmd, pin):
    conn.sendall(compose(MsgType.BRIDGE, args.bridge, cmd, pin))
    while True:
        data = receive(conn, hdr.size)
        if not data:
            log.warning("Data read timeout")
            sys.exit(1)

        msg_type, msg_id, msg_len = hdr.unpack(data)
        if msg_type == MsgType.RSP:
            log.debug("> %2d,%2d    : status %2d", msg_type, msg_id, msg_len)
        elif msg_type == MsgType.HW or msg_type == MsgType.BRIDGE:
            data = receive(conn, msg_len).split("\0")
            log.debug("> %2d,%2d,%2d : %s", msg_type, msg_id, msg_len, "=".join())
            if data[0] == cmd[0]+'w' and data[1] == pin:
                print data[2:]
                break

for op in args.ops:
    cmd = op[0]
    op = op[1:]
    if cmd == 'dw':
        conn.sendall(compose(MsgType.BRIDGE, args.bridge, "dw", op[0], op[1]))
    elif cmd == 'aw':
        conn.sendall(compose(MsgType.BRIDGE, args.bridge, "aw", op[0], op[1]))
    elif cmd == 'vw':
        if len(op) < 2:
            parser.error("virtualWrite needs at least pin and 1 value!")
        conn.sendall(compose(MsgType.BRIDGE, args.bridge, "vw", op[0], *op[1:]))
    elif cmd == 'dr' or cmd == 'ar' or cmd == 'vr':
        do_read(cmd, op[0])
    else:
        log.warning("Wrong command:", cmd)

# Finished

conn.close()
