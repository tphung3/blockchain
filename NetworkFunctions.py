import json
import struct
import socket
import http.client


BUFSIZ = 1024
CATALOG_SERVER = ('catalog.cse.nd.edu', 9097)
NETID = "jrundle"


def find_addr(name):
    conn = http.client.HTTPConnection(*CATALOG_SERVER)
    conn.request("GET", "/query.json")
    data = conn.getresponse().read()

    entries = [d for d in json.loads(data) if d.get('type') == "hashtable" and d.get("project") == name]

    latest_contact = 0
    addr = None

    for entry in entries:
        if entry['lastheardfrom'] > latest_contact:
            latest_contact = entry['lastheardfrom']
            addr = (entry['address'], entry['port'])

    conn.close()
    
    return addr


def send_catalog_update(name, port, netid=NETID):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    data = json.dumps({
        "type": "hashtable",
        "owner": netid,
        "port": port,
        "project": name 
    }).encode()
    s.sendto(data, CATALOG_SERVER)
    s.close()


def send_json(s, json_obj):
    json_str = json.dumps(json_obj)
    size = len(json_str)

    size_bytes = struct.pack("!i", size)
    json_bytes = json_str.encode()

    msg = size_bytes + json_bytes

    try:
        return s.sendall(msg) is None
    except OSError:
        return False


def receive(s, n):
    try:
        return s.recv(n)
    except OSError:
        return 0 


def rec_json(s):
    # Raises ValueError if invalid JSON
    size = rec_int(s)

    if size is None:
        return None
    
    # should also have json ready, so timeout if not
    s.settimeout(0.1)
    json_str = rec_string(s, size)
    s.settimeout(None)

    if json_str is None:
        return None

    try:
        return json.loads(json_str)
    except json.decoder.JSONDecodeError:
        raise ValueError


def rec_string(s, size):
    read = 0
    message = ""
    
    while read < size:
        bufsiz = min(size - read, BUFSIZ)
        content = receive(s, bufsiz)
    
        if not content:
            return None

        message += content.decode(errors='replace')
        read += len(content)
    
    return message


def rec_int(s):
    val = receive(s, 4)
    
    if not val or len(val) != 4:
        return None 

    # recover endianness from network standard
    return struct.unpack("!i", val)[0]

