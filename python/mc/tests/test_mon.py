import unittest
import tempfile
import shutil
from twisted.internet import reactor
from mc import mon

class Handler:
    def __init__(self, reactor, stop_reactor_on_connect_cb = False, accept_connections = True):
        self.reactor = reactor
        self.stop_reactor_on_connect_cb = stop_reactor_on_connect_cb
        self.accept_connections = accept_connections

        self.pid = None
        self.plant = None
        self.name = None
        self.connected = False
        self.connection_count = 0
        self.disconnected = False
        self.rejected = False

    def mcmon_connect_cb(self, plant, name, pid):
        self.connected = True
        self.connection_count = self.connection_count + 1
        self.plant = plant
        self.name = name
        self.pid = pid

        if self.stop_reactor_on_connect_cb:
            reactor.stop()

        return self.accept_connections

    def mcmon_disconnect_cb(self, plant, name, wait_result):
        self.disconnected = True
        self.wait_result = wait_result

    def mcmon_reject_cb(self):
        self.rejected = True

class TestMon(unittest.TestCase):
    def test_client_server_connect(self):
        dd = tempfile.mkdtemp()
        try:
            addr = "{}/socket".format(dd)
            server_cb = Handler(reactor, stop_reactor_on_connect_cb = True)
            client_cb = Handler(reactor)
            server = mon.Server(addr, reactor, server_cb)
            client = mon.Client(addr, reactor, client_cb, "ACME", "foo", 1234)
            client.connect()
            reactor.run()
            self.assertTrue(server_cb.connected)
            self.assertEqual("ACME", server_cb.plant)
            self.assertEqual("foo", server_cb.name)
            self.assertEqual(1234, server_cb.pid)
            server.stop()
        finally:
            shutil.rmtree(dd)
