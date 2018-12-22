import os
import hmac
import json
import time
import signal
import socket
import logging
from collections import OrderedDict

class MediaServer:
    def __init__(self, port, password, root=os.getcwd(), no_hidden=True, filetypes=None, controller=None):
        self.port = port                # port to listen on
        self.password = password        # server secret
        self.root = root                # top level directory of server
        self.no_hidden = no_hidden      # send / play hidden files
        self.filetypes = filetypes      # array of acceptable filetypes
        self.controller = controller    # MediaController

        # create socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', self.port))
        # setup history and state
        self.state = 'NORMAL'       # state can be NORMAL or REPEAT
        self.history_size = 32      # max number of commands to remember
        self.history = OrderedDict()
        # setup pid for daemon
        self.pid = 0

        # attributes that change per connection
        self.client = None
        self.action_id = None
    # runs the server
    def run(self, daemon=False):
        self.pid = 0
        if daemon:
            self.pid = os.fork()
        if self.pid == 0:
            while True:
                try:
                    logging.debug("heartbeat")
                    self._serve(self._recv())
                except KeyboardInterrupt:
                    self.stop()
                    break
        return True
    # stops the server
    def stop(self):
        logging.debug("shutting server down")
        if self.pid != 0:
            os.kill(self.pid, signal.SIGTERM)
            self.pid = 0
    # returns whether the server is running or not
    def is_running(self):
        return self.pid != 0
    # receives a command and authenticates the message
    def _recv(self):
        # loop until we receive a valid command
        while True:
            data, self.client = self.sock.recvfrom(1024)
            try:
                data = data.decode()
                logging.debug("Received: \"%s\"", data)
                if data == "health":
                    logging.debug("alive")
                    self._ack(True, None)
                    continue
                # expect {message: "message", hmac: "HMAC"}
                data = json.loads(data)
                # authenticate
                if self._auth(data) == False:
                    logging.info("Authentication failed for command: \"%s\"", str(data))
                    continue
                data = json.loads(data["message"])
                # set action_id as the time of the request
                self.action_id = data["time"]
                logging.info("Received command: \"%s\"", data)
                return data
            except Exception as e:
                logging.error("Error parsing command: \"%s\"", data)
                logging.error(str(e))
    # sends response back to requester
    def _ack(self, success, response):
        # check if action in history

        # generate message
        t = round(time.time() * 1000)
        msg = json.dumps({"action": self.action_id, "time": t,
                          "result": success, "message": response})
        logging.debug("Sending ACK: \"%s\"", msg)

        h = hmac.new((self.password + str(t)).encode(), msg.encode()).hexdigest()
        self.sock.sendto(json.dumps({"hmac": h, "message": msg}).encode(), self.client)

        # clear client and action_id
        self.client = None
        self.action_id = None
    # authenticates data we received
    def _auth(self, data):
        # expect data = {message: "message", hmac: "HMAC"}
        try:
            m = json.loads(data["message"])
            h = hmac.new((self.password + str(m["time"])).encode(),
                     data["message"].encode()).hexdigest()
            return data["hmac"].lower() == h.lower()
        except: return False
    # take action to (already authenticated) command
    def _serve(self, cmd):
        try:
            command = cmd["command"]
            if command == "play":
                self._ack(self.controller.play(cmd["path"]), None)
            elif command == "pause":
                self._ack(self.controller.pause(cmd["state"]), None)
            elif command == "stop":
                self._ack(self.controller.stop(), None)
            elif command == "seek":
                self._ack(self.controller.seek(cmd["seconds"]), None)
            elif command == "set_volume":
                self._ack(self.controller.set_volume(cmd["volume"]), None)
            elif command == "set_subtitles":
                self._ack(self.controller.set_subtitles(cmd["track"]), None)
            elif command == "fullscreen":
                self._ack(self.controller.fullscreen(cmd["state"]), None)
            elif command == "mute":
                self._ack(self.controller.mute(cmd["state"]), None)
        except KeyError as e:
            self._ack(False, "Expection '%s'" % str(e))
        except:
            self._ack(False, "Not Implemented")
