import os
import logging
import sys
import string
import os.path
import resource

def _max_fd():
    return resource.getrlimit(resource.RLIMIT_NOFILE)[0]

def daemonise(arg_array):
    """Daemonise a new process (fork/exec + re-parent to init)

    """
    executable = arg_array[0]
    if not os.path.isfile(executable):
        raise Exception("Executable \"%s\" does not exist" % executable)

    logging.info("Daemonising command: {}".format(string.join(arg_array, " ")))

    #TODO - use a "with" statement to destruct pipe?
    pipe_r, pipe_w = os.pipe()
    child_pid = os.fork()
    if child_pid == 0:
        #In child
        os.close(pipe_r)
        pid = os.fork()
        if pid == 0:
            os.closerange(3,_max_fd())
            #In grandchild
            try:
                os.execvp(arg_array[0], arg_array)
            except OSError:
                logging.error("Unable to exec command: %s" % (string.join(arg_array, " ")))
                os._exit(1)
        #Still in 1st child
        pipe_w = os.fdopen(pipe_w, 'w')
        pipe_w.write("%d" % pid)
        pipe_w.close()
        os._exit(0)
    #In parent
    os.close(pipe_w)
    pipe_r = os.fdopen(pipe_r, 'r')
    pid = int(pipe_r.read())
    pipe_r.close()
    os.waitpid(child_pid, 0)
    logging.info("Daemonised new process (pid=%d)" % pid)        
    return pid
