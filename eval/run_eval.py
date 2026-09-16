"""평가셋을 에이전트에 넣고 실제 호출된 도구·인자·소요시간을 기록한다. 7주차 완성 대상.

    python eval/run_eval.py --dataset eval/data/sample.jsonl --model <모델 식별자>

출력: eval/runs/<timestamp>_<model>.jsonl (한 줄에 한 건, 입력 + actual + latency)
그 파일을 score.py 에 넘긴다.
"""

from __future__ import annotations

import argparse


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--model", default="baseline")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    raise NotImplementedError(f"7주차: {args.dataset} 를 {args.model} 로 실행하는 부분 구현")


if __name__ == "__main__":
    raise SystemExit(main())
