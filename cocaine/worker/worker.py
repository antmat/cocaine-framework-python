#
#    Copyright (c) 2012+ Anton Tyurin <noxiouz@yandex.ru>
#    Copyright (c) 2013+ Evgeny Safronov <division494@gmail.com>
#    Copyright (c) 2011-2014 Other contributors as noted in the AUTHORS file.
#
#    This file is part of Cocaine.
#
#    Cocaine is free software; you can redistribute it and/or modify
#    it under the terms of the GNU Lesser General Public License as published by
#    the Free Software Foundation; either version 3 of the License, or
#    (at your option) any later version.
#
#    Cocaine is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#    GNU Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public License
#    along with this program. If not, see <http://www.gnu.org/licenses/>.
#

import logging
import socket
import sys

from tornado.ioloop import IOLoop
from tornado.iostream import IOStream

from ._wrappers import default
from .disowntimer import DisownTimer
from .message import Message
from .message import RPC
from .request import RequestStream
from .response import ResponseStream

from ..common import CocaineErrno
from ..decorators import coroutine
from ..detail.io import Timer
from ..detail.util import msgpack_unpacker

DEFAULT_HEARTBEAT_TIMEOUT = 20
DEFAULT_DISOWN_TIMEOUT = 5

log = logging.getLogger("cocaine")


class Worker(object):

    def __init__(self, disown_timeout=DEFAULT_DISOWN_TIMEOUT,
                 heartbeat_timeout=DEFAULT_HEARTBEAT_TIMEOUT,
                 io_loop=None, **kwargs):
        if heartbeat_timeout < disown_timeout:
            raise ValueError("heartbeat timeout must be greater then disown")

        self.io_loop = io_loop or IOLoop.current()
        self.pipe = None
        self.buffer = msgpack_unpacker()

        self.disown_timer = Timer(self.on_disown,
                                  disown_timeout, self.io_loop)

        # it's a fallback mechanism to track
        # that we are disowned even when the main thread is blocked
        # 42 is the universal answer. It's the fallback mechanism
        self.threaded_disown_timer = DisownTimer(disown_timeout * 42)

        self.heartbeat_timer = Timer(self.on_heartbeat_timer,
                                     heartbeat_timeout, self.io_loop)

        self._dispatcher = {
            RPC.HEARTBEAT: self._dispatch_heartbeat,
            RPC.TERMINATE: self._dispatch_terminate,
            RPC.INVOKE: self._dispatch_invoke,
            RPC.CHUNK: self._dispatch_chunk,
            # RPC.ERROR: self._dispatch_error,
            RPC.CHOKE: self._dispatch_choke
        }

        # TBD move into opts
        try:
            self.appname = kwargs.get("app") or sys.argv[sys.argv.index("--app") + 1]
            self.uuid = kwargs.get("uuid") or sys.argv[sys.argv.index("--uuid") + 1]
            self.endpoint = kwargs.get("endpoint") or sys.argv[sys.argv.index("--endpoint") + 1]
        except (ValueError, IndexError) as err:
            raise ValueError("wrong commandline args %s" % err)

        # storehouse for sessions
        self.sessions = {}
        # handlers for events
        self._events = {}
        # protocol
        self.pr = None

        # avoid unnecessary dublicate packing of message
        self._heartbeat_msg = Message(RPC.HEARTBEAT, 1).pack()

    def async_connect(self):

        @coroutine
        def on_connect():
            sock = socket.socket(socket.AF_UNIX)
            log.debug("connecting to %s", self.endpoint)
            try:
                io_stream = IOStream(sock, io_loop=self.io_loop)
                self.pipe = yield io_stream.connect(self.endpoint, callback=None)
                log.debug("connected to %s %s", self.endpoint, self.pipe)
                self.pipe.read_until_close(callback=self.on_failure,
                                           streaming_callback=self.on_message)
            except Exception as err:
                log.error("unable to connect to '%s' %s", self.endpoint, err)
                self.on_failure()
                return

            log.debug("sending handshake")
            self._send_handshake()
            log.debug("sending heartbeat")
            self._send_heartbeat()
            log.debug("start threaded_disown_timer")
            self.threaded_disown_timer.start()

        self.io_loop.add_future(on_connect(), lambda x: None)

    def run(self, binds=None):
        if binds is None:
            binds = {}
        # attach handlers
        for event, handler in binds.items():  # py3
            self.on(event, handler)

        # schedule connection establishment
        self.async_connect()
        # start heartbeat timer
        self.heartbeat_timer.start()

        self.io_loop.start()

    def on(self, event_name, event_handler):
        log.info("registering handler for event %s", event_name)
        try:
            # Try to construct handler.
            closure = event_handler()
        except Exception:
            # If this callable object is not our wrapper - may raise Exception
            closure = default(event_handler)()
            if hasattr(closure, "_wrapped"):
                event_handler = default(event_handler)
        else:
            if not hasattr(closure, "_wrapped"):
                event_handler = default(event_handler)
        log.info("handler for event %s has been attached", event_name)
        self._events[event_name] = event_handler

    # Events
    # healthmonitoring events
    def on_heartbeat_timer(self):
        self._send_heartbeat()

    def on_disown(self):
        try:
            log.error("disowned")
        finally:
            self._stop()

    # General dispatch method
    def on_message(self, data):
        log.debug("on_message %s", data)
        self.buffer.feed(data)
        for i in self.buffer:
            log.debug("unpacked %s", i)
            try:
                message = Message.initialize(i)
                callback = self._dispatcher.get(message.id)
                callback(message)
            except Exception as err:
                log.warn("error %s occured while handling %s", err, i)

    def terminate(self, code, reason):
        log.error("terminated")
        self.pipe.write(Message(RPC.TERMINATE, 1,
                                code, reason).pack())
        self._stop()

    def _dispatch_heartbeat(self, _):
        log.debug("heartbeat has been received. Stop disown timer")
        self.threaded_disown_timer.notify()
        self.disown_timer.stop()

    def _dispatch_terminate(self, msg):
        log.debug("terminate has been received %s %s", msg.errno, msg.reason)
        self.terminate(msg.errno, msg.reason)

    def _dispatch_invoke(self, msg):
        log.debug("invoke has been received %s", msg)
        request = RequestStream(self.io_loop)
        response = ResponseStream(msg.session, self, msg.event)
        try:
            event_closure = self._events.get(msg.event)
            if event_closure is not None:
                event_handler = event_closure()
                event_handler.invoke(request, response, self.io_loop)
                self.sessions[msg.session] = request
            else:
                log.warn("there is no handler for event %s", msg.event)
                response.error(CocaineErrno.ENOHANDLER,
                               "there is no handler for event %s" % msg.event)
        except (ImportError, SyntaxError) as err:
            response.error(CocaineErrno.EBADSOURCE,
                           "source is broken %s" % str(err))
            self.terminate(CocaineErrno.EBADSOURCE,
                           "source is broken")
        except Exception as err:
            log.error("failed to invoke %s %s", err, type(err))
            response.error(CocaineErrno.EINVFAILED,
                           "failed to invoke %s" % err)

    def _dispatch_chunk(self, msg):
        log.debug("chunk has been received %d", msg.session)
        try:
            _session = self.sessions[msg.session]
            _session.push(msg.data)
        except KeyError as err:
            log.warn("no session %s", err)

    def _dispatch_choke(self, msg):
        log.debug("choke has been received %d", msg.session)
        _session = self.sessions.pop(msg.session, None)
        if _session is not None:
            _session.close()

    # On disconnection callback
    def on_failure(self, *args):
        log.error("connection has been lost")
        self.on_disown()

    # Private:
    def _send_handshake(self):
        self.pipe.write(Message(RPC.HANDSHAKE, 1, self.uuid).pack())

    def _send_heartbeat(self):
        self.disown_timer.start()
        log.debug("heartbeat has been sent. Start disown timer")
        self.pipe.write(self._heartbeat_msg)

    def send_choke(self, session):
        self.pipe.write(Message(RPC.CHOKE, session).pack())

    def send_chunk(self, session, data):
        self.pipe.write(Message(RPC.CHUNK, session, data).pack())

    def send_error(self, session, category, code, msg):
        self.pipe.write(Message(RPC.ERROR, session, (category, code), msg).pack())

    def _stop(self):
        self.threaded_disown_timer.stop()
        self.io_loop.stop()
