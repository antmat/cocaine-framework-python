#! /usr/bin/env python

from pprint import pprint
from optparse import OptionParser
import sys
import errno

from cocaine.service.services import Service
from cocaine.exceptions import ServiceError

DESCRIPTION=""
USAGE="USAGE: %prog <app1>@<profile1> <app2>@<profile2> ... <appN>@<profileN> --host [host] --port [port]"



def main(apps, hostname, port):

    try:
        runlist = dict(app.split('@') for app in apps)
    except ValueError:
        print "ERROR: Not all apps have their profiles specified."
        sys.exit(1)

    if not all(runlist):
        print "ERROR: Not all apps have valid names."
        sys.exit(1)

    node = Service("node", hostname, port)
    try:
        pprint(node.perform_sync("start_app", runlist))
    except ServiceError as err:
        print err
        sys.exit(1)


if __name__ == "__main__":
    parser = OptionParser(usage=USAGE, description=DESCRIPTION)
    parser.add_option("--port", type = "int", default=10053, help="Port number")
    parser.add_option("--host", type = "str", default="localhost", help="Hostname")

    (options, args) = parser.parse_args()
    if len(args) == 0:
        print USAGE
        print "Specify applications and profiles"
        sys.exit(1)
    try:
        main(args, options.host, options.port)
    except Exception as err:
        if err.args[0] == errno.ECONNREFUSED:
            print "Invalid endpoint: %s:%d" % (options.host, options.port)
            print USAGE
