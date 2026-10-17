"""Owned TLS termination endpoint: observe the browser, never re-terminate a proxy.

ClientHello input is bounded and length-checked. Normalized fields are local
comparison fields, not a JA4 implementation or an anonymity verdict.
"""
import base64
import hashlib
import socketserver
import ssl
import struct
import threading


class Reader:
    def __init__(self, data):
        self.data = bytes(data)
        self.offset = 0

    def take(self, count):
        if count < 0 or self.offset + count > len(self.data):
            raise ValueError('Truncated TLS vector')
        value = self.data[self.offset:self.offset+count]
        self.offset += count
        return value

    def number(self, count):
        return int.from_bytes(self.take(count), 'big')

    def vector(self, prefix):
        return self.take(self.number(prefix))

    def done(self):
        if self.offset != len(self.data):
            raise ValueError('Trailing TLS vector data')


def words(data):
    if len(data) % 2:
        raise ValueError('Odd TLS integer vector')
    return list(struct.unpack('!'+'H'*(len(data)//2), data))


def grease(value):
    return value >> 8 == value & 255 and value & 0x0f0f == 0x0a0a


def parse_client_hello(data):
    if not 4 <= len(data) <= 256*1024:
        raise ValueError('Unbounded TLS handshake')
    wire = Reader(data)
    if wire.number(1) != 1:
        raise ValueError('Not ClientHello')
    hello = Reader(wire.take(wire.number(3)))
    wire.done()
    version = hello.number(2)
    hello.take(32)  # Random bytes are deliberately excluded from comparisons.
    session = hello.vector(1)
    ciphers = words(hello.vector(2))
    compression = list(hello.vector(1))
    extensions = Reader(hello.vector(2))
    hello.done()
    values = {}
    while extensions.offset < len(extensions.data):
        kind = extensions.number(2)
        if kind in values:
            raise ValueError('Duplicate TLS extension')
        values[kind] = extensions.vector(2)
    groups, points, alpn, versions, signatures, shares, server_names = [], [], [], [], [], [], []
    for kind, payload in values.items():
        r = Reader(payload)
        if kind == 0:
            names = Reader(r.vector(2))
            while names.offset < len(names.data):
                name_type = names.number(1)
                name = names.vector(2)
                if name_type == 0:
                    server_names.append(name.decode('ascii'))
        elif kind in (10, 13):
            vector = words(r.vector(2))
            if kind == 10:
                groups = vector
            else:
                signatures = vector
        elif kind == 11:
            points = list(r.vector(1))
        elif kind == 16:
            protocols = Reader(r.vector(2))
            while protocols.offset < len(protocols.data):
                alpn.append(protocols.vector(1).decode('ascii'))
        elif kind == 43:
            versions = words(r.vector(1))
        elif kind == 51:
            keyshares = Reader(r.vector(2))
            while keyshares.offset < len(keyshares.data):
                group = keyshares.number(2)
                shares.append({'group':group, 'bytes':len(keyshares.vector(2))})
        else:
            continue
        r.done()
    clean = lambda seq: [v for v in seq if not grease(v)]
    ext_order = list(values)
    ja3 = ','.join((str(version), '-'.join(map(str,clean(ciphers))),
                    '-'.join(map(str,clean(ext_order))), '-'.join(map(str,clean(groups))),
                    '-'.join(map(str,points))))
    return {'legacy_version':version, 'session_id_bytes':len(session),
            'cipher_suites':ciphers, 'extension_order':ext_order, 'groups':groups,
            'point_formats':points, 'alpn':alpn, 'supported_versions':versions,
            'signature_algorithms':signatures, 'key_shares':shares,
            'compression_methods':compression, 'server_names':server_names, 'ja3_string':ja3,
            'ja3_md5':hashlib.md5(ja3.encode(), usedforsecurity=False).hexdigest(),
            'normalized':{'legacy_version':version, 'ciphers':clean(ciphers),
                          'extension_types':sorted(clean(ext_order)), 'groups':clean(groups),
                          'point_formats':points, 'alpn':alpn, 'versions':clean(versions),
                          'signatures':clean(signatures),
                          'key_shares':[v for v in shares if not grease(v['group'])],
                          'compression':compression, 'server_names':server_names}}


def frame(kind, flags, stream, payload=b''):
    return len(payload).to_bytes(3,'big')+bytes((kind,flags))+struct.pack('!I',stream)+payload


def parse_http1_request(data):
    if not 4<=len(data)<=65536 or not data.endswith(b'\r\n\r\n'):
        raise ValueError('Unbounded or incomplete HTTP/1 headers')
    lines=data[:-4].split(b'\r\n')
    parts=lines[0].decode('ascii').split(' ')
    if len(parts)!=3 or parts[0]!='GET' or parts[2]!='HTTP/1.1' or not parts[1].startswith('/'):
        raise ValueError('Unexpected owned HTTP/1 request line')
    headers=[]
    for line in lines[1:]:
        if not line or line[:1] in (b' ',b'\t') or b':' not in line or b'\r' in line or b'\n' in line:
            raise ValueError('Invalid HTTP/1 header line')
        name,value=line.split(b':',1)
        if not name or any(c not in b"!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz" for c in name):
            raise ValueError('Invalid HTTP/1 header name')
        headers.append([name.decode('ascii'),value.strip(b' \t').decode('latin1')])
    return {'method':parts[0],'path':parts[1],'version':parts[2],'headers':headers}


class CaptureServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, cert, key, protocol='h2'):
        assert protocol in ('h2','http/1.1')
        self.protocol=protocol
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(cert, key)
        self.context.set_alpn_protocols([protocol])
        self.records = []
        self.lock = threading.Lock()
        self.local = threading.local()

        def message(connection, direction, version, content_type, msg_type, data):
            if direction == 'read' and int(content_type) == 22 and int(msg_type) == 1:
                record = self.local.record
                hello = {'wire_b64':base64.b64encode(data).decode(), 'parsed':parse_client_hello(data)}
                hellos = record.setdefault('client_hellos', [])
                hellos.append(hello)
                # A TLS HelloRetryRequest must not silently replace the first
                # fingerprint with the retried ClientHello.
                if len(hellos) == 1:
                    record['client_hello_b64'] = hello['wire_b64']
                    record['client_hello'] = hello['parsed']
        self.context._msg_callback = message
        super().__init__(address, CaptureHandler)


class CaptureHandler(socketserver.BaseRequestHandler):
    def handle(self):
        record = {'peer_loopback':self.client_address[0]=='127.0.0.1',
                  'frames':[], 'response_streams':[], 'completed':False}
        self.server.local.record = record
        sock = None
        try:
            self.request.settimeout(10)
            sock = self.server.context.wrap_socket(self.request, server_side=True)
            record.update(alpn=sock.selected_alpn_protocol(), tls_version=sock.version())
            if record['alpn'] != self.server.protocol:
                raise ValueError('Unexpected actual ALPN negotiation')
            if record['alpn']=='http/1.1':
                data=b''
                while not data.endswith(b'\r\n\r\n'):
                    part=sock.recv(1)
                    if not part:raise EOFError('Owned HTTP/1 client closed')
                    data+=part
                    if len(data)>65536:raise ValueError('Unbounded HTTP/1 request')
                record['http1_request_b64']=base64.b64encode(data).decode()
                record['http1_request']=parse_http1_request(data)
                body=b'<!doctype html><title>Owned transport</title><p>Owned transport ready</p>'
                sock.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: '+str(len(body)).encode()+b'\r\nConnection: close\r\n\r\n'+body)
                record['completed']=True
                return
            def read(count):
                data = b''
                while len(data) < count:
                    part = sock.recv(count-len(data))
                    if not part:
                        raise EOFError('Owned client closed')
                    data += part
                return data
            if read(24) != b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n':
                raise ValueError('Missing HTTP/2 preface')
            record['http2_preface'] = True
            sock.sendall(frame(4,0,0))
            for _ in range(64):
                header = read(9)
                size = int.from_bytes(header[:3],'big')
                if size > 1024*1024:
                    raise ValueError('Unbounded HTTP/2 frame')
                kind, flags = header[3:5]
                stream = int.from_bytes(header[5:],'big') & 0x7fffffff
                payload = read(size)
                row = {'type':kind,'flags':flags,'stream':stream,'length':size}
                if kind == 4 and not flags & 1:
                    if stream or len(payload) % 6:
                        raise ValueError('Invalid SETTINGS frame')
                    row['settings'] = [list(struct.unpack('!HI',payload[i:i+6])) for i in range(0,len(payload),6)]
                    sock.sendall(frame(4,1,0))
                if kind == 8:
                    if size != 4:
                        raise ValueError('Invalid WINDOW_UPDATE')
                    row['increment'] = int.from_bytes(payload,'big') & 0x7fffffff
                if kind == 1:
                    # Retain HPACK bytes; do not claim decoded header order.
                    row['header_block_b64'] = base64.b64encode(payload).decode()
                record['frames'].append(row)
                if kind == 1 and flags & 4:
                    body = b'<!doctype html><title>Owned transport</title><p>Owned transport ready</p>'
                    sock.sendall(frame(1,4,stream,b'\x88')+frame(0,1,stream,body))
                    record['response_streams'].append(stream)
                    record['completed'] = True
                if kind == 7:
                    break
        except (EOFError, ConnectionError, TimeoutError, ssl.SSLError) as error:
            record['close_reason'] = type(error).__name__
        except Exception as error:
            record['error'] = type(error).__name__+': '+str(error)
        finally:
            if sock:
                sock.close()
            with self.server.lock:
                self.server.records.append(record)
