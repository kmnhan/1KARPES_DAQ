import logging
import sys

log = logging.getLogger("elliptec")
log.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
# handler = logging.FileHandler(
#     f"D:/daq_logs/{log.name}.log",
#     mode="a",
#     encoding="utf-8",
# )
handler.setFormatter(
    logging.Formatter("%(asctime)s | %(name)s | %(levelname)s - %(message)s")
)
log.addHandler(handler)


# Log all uncaught exceptions
def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    log.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = handle_exception
