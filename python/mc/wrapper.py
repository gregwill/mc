import argparse
from twisted.internet import reactor, protocol, defer
from mc import mon, util
import logging

retry_interval = 5
log = logging.getLogger("wrapper")

class MyProcessProtocol(protocol.ProcessProtocol):
    def __init__(self, deferred):
        self.deferred = deferred

    def processEnded(self, reason):
        log.info("Child exited with exitStatus={}, signal={}".format(reason.value.exitCode, reason.value.signal))
        self.deferred.callback(reason.value.status)

class Wrapper:
    def __init__(self, addr, plant, name, command):
        self.addr = addr
        self.plant = plant
        self.name = name
        self.shutting_down = False
        self.wait_result = None

        self.spawn(command)

        self.connect()

    def spawn(self, command):
        log.info("Spawning command: {}".format(" ".join(command)))
        self.proc_deferred = defer.Deferred()
        self.proc_deferred.addCallback(self.child_died)
        self.death = None
        self.process_protocol = MyProcessProtocol(self.proc_deferred)
        self.process = reactor.spawnProcess(self.process_protocol, command[0], command, childFDs={0:0, 1:1, 2:2, 3:'r'})
        self.pid = self.process.pid
        log.info("Command spawned (pid={})".format(self.pid))

    def child_died(self, value):
        self.proc_deferred = None
        self.process = None
        self.wait_result = value
        if self.mon_client.notify_death(value):
            self.shutdown()
        else:
            log.info("Delaying shutdown whilst we try and report death to mcagent")

    def shutdown(self):
        log.info("shutting down")
        self.mon_client.disconnect()
        self.shutting_down = True

    def connect(self):
        if not self.shutting_down:
            log.info("Connecting to mcagent on {}".format(self.addr))
            self.mon_client = mon.Client(self.addr, reactor, self, self.plant, self.name, self.pid, self.wait_result)
            self.connect_deferred = self.mon_client.connect()
            self.connect_deferred.addErrback(self.connect_failed)

    def retry(self):
        log.info("Will retry mcmon connection to mcagent in {}s".format(retry_interval))
        reactor.callLater(retry_interval, self.connect)
        
    def connect_failed(self, failure):
        log.error("Failed to connect to mcagent on {}: {}".format(self.addr,failure))
        self.retry()

    def mcmon_accept_cb(self):
        if self.process is None:
            log.info("Finally reported exit status - shutting down")
            self.shutdown()

    def mcmon_reject_cb(self):
        if self.process is None:
            log.error("mcmon was rejected, so unable to send death certificate")
            self.shutdown()
        else:
            log.info("Sending SIGKILL to child pid {} and waiting to die".format(self.pid))
            self.process_protocol.transport.signalProcess('KILL')

    def mcmon_disconnect_cb(self):
        if self.shutting_down:
            reactor.stop()
        else:
            self.retry()
        
def main():
    util.init_logging_to_stderr()

    parser = argparse.ArgumentParser(description='mc wrapper - agent wraps all commands in this utility, whose job it is to monitor the application and report status back to the agent')
    parser.add_argument("--socket", help="unix domain socket", required=True)
    parser.add_argument("--plant", help="plant name", required=True)
    parser.add_argument("--name", help="application name", required=True)
    parser.add_argument("command", help="command to run", nargs="*")
    args = parser.parse_args()
    wrapper = Wrapper(args.socket, args.plant, args.name, args.command)
    reactor.run()

if __name__ == "__main__":
    main()
