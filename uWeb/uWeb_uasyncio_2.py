import usocket as socket
import ujson as json
import gc
import network
import sys
import asyncio
import uselect as select


class uWeb:
    version = 'uWeb-v1.1'
    GET = 'GET'
    POST = 'POST'
    PUT = 'PUT'
    DELETE = 'DELETE'

    OK = b"200 OK"
    NOT_FOUND = b"404 Not Found"
    FOUND = b"302 Found"
    FORBIDDEN = b"403 Forbidden"
    BAD_REQUEST = b"400 Bad Request"
    ERROR = b"500 Internal Server Error"

    MIME_TYPES = {
        'css': 'text/css',
        'html': 'text/html',
        'jpeg': 'image/jpeg',
        'jpg': 'image/jpeg',
        'js': 'text/javascript',
        'json': 'application/json',
        'rtf': 'application/rtf',
        'svg': 'image/svg+xml'
    }
    
    
    def __init__(self, host="0.0.0.0", port=8123, backlog=5, timeout=20):
        self.host = host
        self.port = port
        self.backlog = backlog
        self.timeout = timeout
        self.routes() #init empty routes_dict

    async def run(self, log=True):
        self.log = log
        print("Awaiting client connection.")
        self.cid = 0
        self.server = await asyncio.start_server(
            self.run_client, self.host, self.port, self.backlog
        )
        while True:
            await asyncio.sleep(0)

    async def run_client(self, sreader, swriter):
        self.cid += 1
        self.sreader = sreader
        self.swriter = swriter
        print("Got connection from client", self.cid)
        try:
            while True:
                try:
                    self.request_line = await asyncio.wait_for(sreader.readline(), self.timeout)
                    if bool(self.request_line):  #check if request not empty
                        if self.log:
                            print(self.request_line.decode().strip())
                        await asyncio.wait_for(self.resolveRequestLine(), self.timeout)
                        await asyncio.wait_for(self.processRequest(), self.timeout)
                        await asyncio.wait_for(self.router(), self.timeout)
                except asyncio.TimeoutError:
                    print("timeout")
                    self.request_line = b""
                if self.request_line == b"":
                    raise OSError
                await swriter.drain() # Echo back
                await swriter.wait_closed() #Close writer
        except OSError:
            pass
        print("Client {} disconnect.".format(self.cid))
        await sreader.wait_closed()
        print("Client {} socket closed.".format(self.cid))
    
    #BACKEND SERVER METHODS
    def routes(self, routes={}):
        # set routes dict
        self.routes_dict = routes
    
    async def router(self):
        if len(self.routes_dict) == 0:
            self.render('welcome.html')
        elif self.request_command:
            if (self.request_command, self.request_path) in self.routes_dict.keys():
                # check for valid route
                self.routes_dict[(self.request_command, self.request_path)]()
            elif ('.' in self.request_path):
                #send file to client
                self.sendFile(self.request_path[1:])
            else:
                self.render('404.html', layout=None, status=self.NOT_FOUND)
        else:
            self.render('505.html', layout=None, status=self.ERROR)
            
    async def processRequest(self):
        #process request from client --> extract headers + body
        raw_headers = []
        self.request_headers = {}

        #extract headers
        while True:
            h = await asyncio.wait_for(self.sreader.readline(), self.timeout)
            if h == b"" or h == b"\r\n":
                break
            if self.log:
                print(h.decode().strip())
            raw_headers.append(h)
        for header in raw_headers:
            split_header = header.decode().strip().split(': ')
            self.request_headers[split_header[0]] = split_header[1]

        # extract body if its a POST request
        if self.request_command == self.POST:
            await asyncio.wait_for(sreader.readline(), self.timeout)
            request_body_raw = await asyncio.wait_for(self.sreader.read(int(self.request_headers['Content-Length'])), self.timeout)
            self.request_body = request_body_raw.decode()
            if self.log:
                print(self.request_body)

    async def resolveRequestLine(self):
        # parse request line from client
        l = self.request_line
        req_line = l.decode().strip().split(' ')
        if len(req_line) > 1:
            self.request_command = req_line[0]
            self.request_path = req_line[1]
            self.request_http_ver = req_line[2]
            return True
        else:
            return False
        
    def render(self, html_file, layout='layout.html', variables=False, status=OK):
        # send HTML file to client
        try:
            if layout:
                # layout rendering
                file = layout
                with open(layout, 'r') as f:
                    gc.collect()
                    self.sendStatus(status)
                    self.sendHeaders({'Content-Type': 'text/html'})
                    self.send(b'\n')
                    for line in f:
                        if '{{yield}}' in line:
                            splitted = line.split('{{yield}}')
                            self.send(splitted[0].encode())
                            with open(html_file, 'r') as f:
                                for line in f:
                                    if variables:
                                        for var_name, value in variables.items():
                                            line = line.replace("{{%s}}" % var_name, str(value))
                                    self.send(line.encode())
                            self.send(splitted[1].encode())
                        else: 
                            self.send(line.encode())
            else:
                # no layout rendering
                gc.collect()
                self.sendStatus(status)
                self.sendHeaders({'Content-Type': 'text/html'})
                self.send(b'\n')
                file = html_file
                with open(html_file, 'r') as f:
                    for line in f:
                        if variables:
                            for var_name, value in variables.items():
                                line = line.replace("{{%s}}" % var_name, str(value))
                        self.send(line.encode())
            self.send(b'\n\n')
        except Exception as e:
            if e.args[0] == 2:
                #catch file not found
                print('No such file: %s' % file)
                self.render('500.html', layout=None, status=self.ERROR)
            else:
                sys.print_exception(e)
                
    def sendJSON(self, dict_to_send={}):
        print("send json")
        # send JSON data to client
        self.sendStatus(self.OK)
        self.sendHeaders({'Content-Type': 'application/json'})
        self.sendBody(json.dumps(dict_to_send))

    def sendFile(self, filename):
        # send file(ie: js, css) to client
        name, extension = filename.split('.')
        try:
            if extension in self.supported_file_types:
                # check if included in allowed file types
                with open(filename, 'r') as f:
                    self.sendStatus(self.OK)
                    if extension in self.MIME_TYPES.keys():
                        self.sendHeaders({'Content-Type': self.MIME_TYPES[extension]}) # send content type
                    self.send(b'\n')
                    for line in f:
                        self.send(line.encode())
                self.send(b'\n\n')
            else:
                self.sendStatus(self.ERROR)
                print('File: %s is not an allowed file' % filename)
        except Exception as e:
            self.sendStatus(self.NOT_FOUND)
            print('File: %s was not found, so 404 was sent to client.' % filename)

    def sendStatus(self, status_code):
        # send HTTP header w/ status to client
        response_line = b"HTTP/1.1 "
        self.send(response_line + status_code + b'\n')

    def sendHeaders(self, headers_dict={}):
        # send HTTP headers to client
        for key, value in headers_dict.items():
            self.send(b"%s: %s\n" % (key.encode(), value.encode()))

    def sendBody(self, body_content):
        # send HTTP body content to client
        self.send(b'\n' + body_content + b'\n\n')

    def setSupportedFileTypes(self, file_types = ['js', 'css']):
        #set allowed file types to be sent if requested
        self.supported_file_types = file_types
        
    def readFile(self, file):
        # read file and encode
        try:
            with open(file, 'r') as f:
                return ''.join(f.readlines()).encode()
        except Exception as e:
            print(e)

    def send(self, content):
        # send to client @ socket-level
        self.swriter.write(content)


    async def close(self):
        print("Closing server")
        self.server.close()
        await self.server.wait_closed()
        print("Server closed.")

def loadJSON(string):
    # turn JSON string to dict
    return json.loads(string)
