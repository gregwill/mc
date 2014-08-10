from twisted.internet.protocol import Factory, ReconnectingClientFactory
from twisted.protocols.basic import Int32StringReceiver
from twisted.internet.endpoints import UNIXServerEndpoint, UNIXClientEndpoint
from twisted.internet import reactor, defer
from mc.proto import mcmon_pb2 as proto
import mc.util
import logging
import sys
import argparse

#States
CONNECTED = 0
ACCEPTED  = 1
REJECTED  = 2
DEAD      = 3

class ServerProtocol(Int32StringReceiver):
    def __init__(self, callback, addr):
        self.callback = callback
        self.addr = addr

    def connectionMade(self):
        self.state    = CONNECTED
        logging.debug("New mcmon connection received on {}".format(self.addr))

    def connectionLost(self, reason):
        if self.state == CONNECTED:
            logging.info("Unknown client disconnected")
        else:
            logging.info("{} in {} disconnected".format(self.name, self.plant))
        if self.state == ACCEPTED:
            self.callback.mcmon_disconnect_cb(self.plant, self.name, self.wait_result)

    def stringReceived(self, msg):
        req = proto.Request()
        req.ParseFromString(msg)
        if req.type == proto.Request.REGISTER:
            reg = req.Extensions[proto.Register.request]
            self.plant = reg.plant
            self.name  = reg.name
            self.pid   = reg.pid
            self.wait_result = None
            resp = proto.Response()
            allow = self.callback.mcmon_connect_cb(reg.plant, reg.name, reg.pid)
            if allow:
                logging.info("Accepting mcmon connection: {}".format(str(reg).replace("\n", ", ")))
                self.state = ACCEPTED
                resp.type = proto.Response.ACCEPT
            else:
                logging.warn("Rejecting mcmon connection: {}".format(str(reg).replace("\n", ", ")))
                self.state = REJECTED
                resp.type = proto.Response.REJECT
            self.sendString(resp.SerializeToString())
        elif req.type == proto.Request.DEAD:
            dead = req.Extensions[proto.Dead.request]
            self.wait_result = dead.wait_result
            logging.info("{} in {} reported wait result {}".format(self.name, self.plant, self.wait_result))
            pass
        else:
            logging.error("Unknown request type {}".format(req.type))

class ServerFactory(Factory):
    def __init__(self, callback):
        self.callback = callback

    def buildProtocol(self, addr):
        print "Building ServerProtocol"
        return ServerProtocol(self.callback, addr)

class Server:
    def __init__(self, addr, reactor, callback):
        self.addr = addr
        self.reactor = reactor
        self.factory = ServerFactory(callback)
        self.endpoint = UNIXServerEndpoint(reactor, addr)
        self.listen_deferred = self.endpoint.listen(self.factory)
        logging.info("mcmon server listening on {}".format(addr))

    def stop(self):
        self.stop_deferred = self.endpoint.stop_listening()
        return self.stop_deferred

class ClientProtocol(Int32StringReceiver):
    def __init__(self, callback, plant, name, pid, wait_result):
        self.callback = callback
        self.plant = plant
        self.name = name
        self.pid = pid
        self.wait_result = wait_result
        self.disconnecting = False

    def connectionMade(self):
        req = proto.Request()
        req.type = proto.Request.REGISTER
        reg = req.Extensions[proto.Register.request]
        reg.plant = self.plant
        reg.name  = self.name
        reg.pid   = self.pid
        if (self.wait_result is not None):
            reg.wait_result = self.wait_result
        try:
            self.sendString(req.SerializeToString())
        except:
            logging.exception("Cannot send register message")
        self.state = CONNECTED
        logging.info("Sending registration message: {}".format(str(reg).replace("\n", ", ")))
    
    def stringReceived(self, msg):
        resp = proto.Response()
        resp.ParseFromString(msg)
        if resp.type == proto.Response.ACCEPT:
            logging.info("mcmon server accepted registration")
            self.state = ACCEPTED;
            self.callback.mcmon_accept_cb()
        elif resp.type == proto.Response.REJECT:
            logging.error("mcmon server rejected registration")
            self.state = REJECTED
            self.callback.mcmon_reject_cb()
        else:
            logging.error("Unknown mcmon response type {}".format(resp.type))

    def notify_death(self, wait_result):
        req = proto.Request()
        req.type = proto.Request.DEAD
        dead = req.Extensions[proto.Dead.request]
        dead.wait_result = wait_result
        self.sendString(req.SerializeToString())
        self.state = DEAD
        logging.info("Sending death certificate (wait_result={})".format(wait_result))

    def disconnect(self):
        self.disconnecting = True
        self.transport.loseConnection()

    def connectionLost(self, reason):
        if self.disconnecting:
            logging.info("Disconnected from mcmon server")
        else:
            logging.error("Connection to mcmon server lost - {}".format(reason))
        self.callback.mcmon_disconnect_cb()

class ClientFactory(ReconnectingClientFactory):
    def __init__(self, callback, plant, name, pid, wait_result, deferred):
        self.callback = callback
        self.plant = plant
        self.name = name
        self.pid = pid
        self.wait_result = wait_result
        self.deferred = deferred

    def buildProtocol(self, addr):
        self.resetDelay()
        p = ClientProtocol(self.callback, self.plant, self.name, self.pid, self.wait_result)
        self.deferred.callback(p)
        return p

class Client:
    def __init__(self, addr, reactor, callback, plant, name, pid, wait_result):
        self.addr = addr
        self.reactor = reactor
        self.protocol = None
        self.deferred = defer.Deferred()
        self.deferred.addCallback(self.connected)
        self.factory = ClientFactory(callback, plant, name, pid, wait_result, self.deferred)
        self.endpoint = UNIXClientEndpoint(reactor, addr)
        
    def connect(self):
        return self.endpoint.connect(self.factory)

    def disconnect(self):
        if self.protocol is not None:
            self.protocol.disconnect()
        
    def connected(self, protocol):
        self.protocol = protocol

    def notify_death(self, wait_result):
        """Returns true if death ceritificate has been sent, false otherwise

        """
        if self.protocol is None:
            logging.error("Cannot report exit status because not connected")
            return False
        elif self.protocol.state == ACCEPTED:
            self.protocol.notify_death(wait_result)
        else:
            logging.info("Not notifying server of death because connection is not in ACCEPTED state (state = {})".format(self.protocol.state))
        return self.protocol.state >= ACCEPTED

class NullHandler:
    def __init__(self, reject):
        self.reject = reject

    def mcmon_connect_cb(self, plant, name, pid):
        return not self.reject

    def mcmon_disconnect_cb(self, plant, name, wait_result):
        pass

def main():
    parser = argparse.ArgumentParser(description='mcmon')
    parser.add_argument("--socket", help="unix domain socket", required=True)
    parser.add_argument("--reject", help="Reject mcmon connections", action="store_true")
    args = parser.parse_args()

    mc.util.init_logging_to_stderr()

    handler = NullHandler(args.reject)
    server = Server(args.socket, reactor, handler)
    reactor.run()

if __name__ == "__main__":
    main()
