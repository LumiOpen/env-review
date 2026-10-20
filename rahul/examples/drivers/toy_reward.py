"""Small deterministic reward driver for protocol and relation examples."""

import json
import math
import sys


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("state/action must be finite numbers")
    return float(value)


def main():
    payload = json.load(sys.stdin)
    data = payload["case"]["input"]
    if "answer" in data:
        answer = data["answer"]
        if not isinstance(answer, str):
            raise ValueError("answer must be text")
        reward = 1.0 if "," in answer else 0.0
        details = {"mode": "format", "answer": answer}
    else:
        position = finite(data["state"]["position"])
        action = finite(data["action"])
        reward = max(0.0, min(1.0, (position + action) / 10.0))
        details = {"mode": "state", "position": position, "action": action}
    print(json.dumps({"reward": reward, "details": details}, allow_nan=False))


if __name__ == "__main__":
    main()
