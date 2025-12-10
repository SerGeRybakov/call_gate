from datetime import timedelta
from multiprocessing import Process
from os import getpid

from call_gate import CallGate, ThrottlingError


def worker(gate: CallGate) -> None:
    pid = getpid()
    try:
        gate.update(1)  # ok
        gate.update(1)  # ok
        gate.update(1, throw=True)  # may exceed limits across processes
    except ThrottlingError as exc:
        print(f"[{pid=}] limit: {exc}")
    finally:
        print(f"[{pid=}] state: {gate.state}")


def main() -> None:
    gate = CallGate(
        "shared_storage_demo",
        timedelta(seconds=1),
        timedelta(milliseconds=500),
        gate_limit=3,
        frame_limit=2,
        storage="shared",
    )
    p1 = Process(target=worker, args=(gate,))
    p2 = Process(target=worker, args=(gate,))
    p1.start()
    p2.start()
    p1.join()
    p2.join()

    print(f"[pid={getpid()}] final state: {gate.state}")


if __name__ == "__main__":
    main()
