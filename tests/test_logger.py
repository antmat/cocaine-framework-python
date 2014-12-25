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

from tornado.ioloop import IOLoop
from tornado import gen

from cocaine.detail.logger import _Logger


def test_logger():
    io = IOLoop.current()
    verbosity_level = 0
    l = _Logger()

    @gen.coroutine
    def set_verbosity():
        ch = yield l.set_verbosity(verbosity_level)
        res = yield ch.rx.get()
        raise gen.Return(res)

    empty_resp = io.run_sync(set_verbosity)
    assert empty_resp == [], empty_resp
    verbosity = io.run_sync(io.run_sync(l.verbosity).rx.get)
    assert verbosity == verbosity_level, verbosity
    l.emit(verbosity_level, "nosetest", "test_message", {"attr1": 1, "attr2": 2})
    l.debug("DEBUG_MSG", {"A": 1, "B": 2})
    l.info("INFO_MSG", {"A": 1, "B": 2})
    l.warning("WARNING_MSG", {"A": 1, "B": 2})
    l.error("ERROR_MSG", {"A": 1, "B": 2})