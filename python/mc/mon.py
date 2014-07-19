from twisted.internet.protocol import Factory, ReconnectingClientFactory
from twisted.protocols.basic import Int32StringReceiver
from twisted.internet.endpoints import UNIXServerEndpoint, UNIXClientEndpoint
from mc.proto import mcmon_pb2 as proto
import logging
import sys

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
                logging.info("Accepting mcmon connection: {}".format(str(reg)))
                self.state = ACCEPTED
                resp.type = proto.Response.ACCEPT
            else:
                logging.warn("Rejecting mcmon connection: {}".format(str(reg)))
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
        self.endpoint.listen(self.factory)
        logging.info("mcmon server listening on {}".format(addr))

class ClientProtocol(Int32StringReceiver):
    def __init__(self, callback, plant, name, pid):
        self.callback = callback
        self.plant = plant
        self.name = name
        self.pid = pid

    def connectionMade(self):
        req = proto.Request()
        req.type = proto.Request.REGISTER
        reg = req.Extensions[proto.Register.request]
        reg.plant = self.plant
        reg.name  = self.name
        reg.pid   = self.pid
        try:
            self.sendString(req.SerializeToString())
        except:
            logging.exception("Cannot send register message")
        self.state = CONNECTED
        logging.info("Sending registration message: {}".format(str(reg)))
    
    def stringReceived(self, msg):
        resp = proto.Response()
        resp.ParseFromString(msg)
        if resp.type == proto.Response.ACCEPT:
            logging.info("mcmon server accepted")
            self.state = ACCEPTED;
        elif resp.type == proto.Response.REJECT:
            logging.error("mcmon server rejected registration - shutting down")
            self.state = REJECTED
            self.callback.mcmon_reject_cb()
            self.transport.lose_connection()
        else:
            logging.error("Unknown mcmon response type {}".format(resp.type))

    def notify_death(self, wait_result):
        req = proto.Request()
        req.type = proto.Request.DEAD
        dead = req.Extensions[proto.Dead.request]
        dead.wait_result = wait_result
        self.sendString(req.SerializeToString())
        self.state = DEAD

    def connectionLost(self, reason):
        logging.error("Connection to mcmon server lost")

class ClientFactory(ReconnectingClientFactory):
    def __init__(self, callback, plant, name, pid):
        self.callback = callback
        self.plant = plant
        self.name = name
        self.pid = pid
        self.connection = None

    def buildProtocol(self, addr):
        print("Constructing ClientProtocol")
        self.connection = ClientProtocol(self.callback, self.plant, self.name, self.pid)
        print("Constructing ClientProtocol2")
        return self.connection

    def clientConnectionLost(self, connector, reason):
        if self.connection.state == REJECTED or self.connection.state == DEAD:
            self.stopTrying()
        self.connection = None
        ReconnectingClientFactory.clientConnectionLost(self, connector, reason)

class Client:
    def __init__(self, addr, reactor, callback, plant, name, pid):
        self.addr = addr
        self.reactor = reactor
        self.factory = ClientFactory(callback, plant, name, pid)
        self.endpoint = UNIXClientEndpoint(reactor, addr)
        self.endpoint.connect(self.factory)

    def notify_death(wait_result):
        connection = self.factory.connection
        if connection is None:
            logging.error("Cannot report exit status because not connected")
        elif connection.state == ACCEPTED:
            connection.notify_death(wait_result)
        else:
            logging.info("Not notifying server of death because connection is not in ACCEPTED state (state = {})".format(connction.state))
