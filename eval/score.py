"""run_eval.py 결과를 채점한다. 지표 정의는 eval/README.md.

python eval/score.py eval/runs/<file>.jsonl --out reports/data/<name>.csv
"""

from __future__ import annotations


def tool_acc(expected: dict, actual: dict) -> bool:
    return expected.get("tool") == actual.get("tool")


def arg_acc(expected: dict, actual: dict) -> bool:
    """expected.args 에 적힌 인자만 비교. 되물었어야 하는 케이스는 ask 여부로 판단."""
    if expected.get("ask"):
        return bool(actual.get("ask"))
    if expected.get("tool") is None:
        return actual.get("tool") is None
    exp_args = expected.get("args", {})
    act_args = actual.get("args", {}) or {}
    return all(act_args.get(k) == v for k, v in exp_args.items())


def main() -> int:
    raise NotImplementedError("7주차: 집계와 csv/md 출력 구현")


if __name__ == "__main__":
    raise SystemExit(main())
