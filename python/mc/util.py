
def init_twisted_logging():
    from twisted.python import log
    observer = log.PythonLoggingObserver(loggerName='twisted')
    observer.start()

def init_logging_to_stderr():
    import logging
    rootLogger = logging.getLogger()
    rootLogger.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)

    # create formatter
    formatter = logging.Formatter('%(asctime)s.%(msecs)d %(process)d %(name)s %(levelname)s - %(message)s (%(pathname)s:%(lineno)d)', '%Y%m%d %H:%M:%S')

    # add formatter to ch
    ch.setFormatter(formatter)

    # add ch to logger
    rootLogger.addHandler(ch)

    twisted_logger = logging.getLogger('twisted')
    twisted_logger.setLevel(logging.DEBUG)
    init_twisted_logging()
