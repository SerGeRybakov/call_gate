from datetime import timedelta

from call_gate import CallGate, ThrottlingError


def main() -> None:
    gate = CallGate(
        "simple_storage",
        timedelta(seconds=1),
        timedelta(milliseconds=500),
        gate_limit=3,
        frame_limit=2,
        storage="simple",
    )

    try:
        gate.update(2)  # reach frame limit
        gate.update(throw=False)  # exceed frame limit, wait and increment 1
        gate.update(throw=True)  # exceed gate limit, raise
    except ThrottlingError as exc:
        print(exc)
    print(gate.state)


if __name__ == "__main__":
    main()
