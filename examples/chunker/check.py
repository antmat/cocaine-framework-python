#!/usr/bin/env python
import os
import sys

from tornado.ioloop import IOLoop

from cocaine.protocol import ChokeEvent
from cocaine.services import Service


__author__ = 'EvgenySafronov <division494@gmail.com>'


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Usage: chunker.py NUMBER_OF_CHUNKS')
        exit(os.EX_USAGE)

    def test():
        yield service.connect()
        deferred = yield service.enqueue('spam', str(sys.argv[1]))
        try:
            while True:
                chunk = yield deferred
                if chunk == 'Done':
                    break
        except ChokeEvent:
            pass
        except Exception as err:
            print('Error: {0}'.format(err))
        finally:
            loop.stop()

    service = Service('chunker')
    test()
    loop = IOLoop.current()
    loop.start()
