
import mc.system
import tempfile
import unittest
import os.path
import shutil

class TestSystem(unittest.TestCase):
    def test_daemonise_success(self):
        dd = tempfile.mkdtemp()
        ff = dd + "/foo"
        cmd = [ '/usr/bin/touch', ff ]
        pid = mc.system.daemonise(cmd)
        
        #Wait for it to die
        try:
            while os.kill(pid, 0):
                pass
        except OSError:
            pass

        for i in xrange(1000):
            if os.path.isfile(ff):
                break

        self.assertTrue(os.path.isfile(ff))

        shutil.rmtree(dd)

    def test_daemonise_invalid_command(self):
        self.assertRaisesRegexp(Exception, "does not exist", mc.system.daemonise, ['/sdfsd/fs/df/dsg/sdg'])
