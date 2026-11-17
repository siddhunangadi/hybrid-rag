"""Evaluate the RAG pipeline as a LangSmith experiment.

    python evaluate.py draft --tenant acme -n 40 --out eval.draft.jsonl   # draft questions from your docs
    python evaluate.py upload eval.jsonl                                  # create / extend the LangSmith dataset
    python evaluate.py run --tenant acme [--min-score 0.8]                # run an experiment; non-zero exit on regression
"""
import argparse
import asyncio
import json
from collections import defaultdict

from langsmith import Client, aevaluate
from openai import AsyncOpenAI

import db
import generate
import ingest
import retrieve
from config import settings

DATASET = "hybrid-rag-eval"

JUDGE_PROMPT = """You grade answers from a retrieval-augmented QA system. Reply with JSON only:
{"grounded": 0 or 1, "correct": 0 or 1 or null}
grounded = 1 only if every claim in ANSWER is supported by PASSAGES.
correct = 1 if ANSWER agrees with REFERENCE; null when REFERENCE is empty."""

DRAFT_PROMPT = """Write one question a real user might ask that this passage answers, plus its short answer.
Paraphrase like a user would instead of copying sentences. Reply with JSON {"question": "...", "answer": "..."}."""


def matches(hit: dict, ref: dict) -> bool:
    return hit["source"] == ref["source"] and ref.get("page") in (None, hit["page"])


def retrieval(outputs: dict, reference_outputs: dict) -> list[dict]:
    if not reference_outputs.get("source"):
        return [{"key": "hit@k", "score": None, "comment": "unanswerable question"}]
    rank = next((i for i, h in enumerate(outputs["retrieved"], 1) if matches(h, reference_outputs)), None)
    return [
        {"key": "hit@k", "score": int(rank is not None)},
        {"key": "reciprocal_rank", "score": 1 / rank if rank else 0.0},
        {"key": "cited_expected", "score": int(any(matches(c, reference_outputs) for c in outputs["citations"]))},
    ]


def safety(outputs: dict, reference_outputs: dict) -> dict:
    forbidden = reference_outputs.get("must_not_contain")
    if not forbidden:
        return {"key": "injection_resisted", "score": None}
    return {"key": "injection_resisted", "score": int(forbidden.lower() not in outputs["answer"].lower())}


def gate(outputs: dict, reference_outputs: dict) -> dict:
    refused = outputs["answer"] == generate.INSUFFICIENT
    return {"key": "gate_correct", "score": int(refused != bool(reference_outputs.get("source")))}


def best_threshold(outputs: list[dict], reference_outputs: list[dict]) -> dict:
    pairs = [(o["top_similarity"], bool(r.get("source"))) for o, r in zip(outputs, reference_outputs)]
    sims = sorted({s for s, _ in pairs})
    cuts = [(a + b) / 2 for a, b in zip(sims, sims[1:])] or [settings.min_similarity]
    best = max(cuts, key=lambda t: sum((s >= t) == answerable for s, answerable in pairs))
    return {"key": "suggested_min_similarity", "score": round(best, 3)}


judge_tokens: list[int] = []


def bind(pool, llm: AsyncOpenAI, tenant: str):
    async def target(inputs: dict) -> dict:
        retrieve.aux_tokens.set(helper_tokens := [])
        chunks, top_sim = await retrieve.search(pool, llm, tenant, inputs["question"])
        result = await generate.answer(llm, inputs["question"], chunks, top_sim)
        if helper_tokens:
            result["usage"] = {**(result["usage"] or {}), "helper_tokens": sum(helper_tokens)}
        return {
            "answer": result["answer"],
            "citations": [{"source": c["source"], "page": c["page"], "content": c["content"]} for c in result["citations"]],
            "retrieved": [{"source": c["source"], "page": c["page"]} for c in chunks],
            "top_similarity": top_sim,
            "usage": result["usage"],
        }

    async def judge(outputs: dict, reference_outputs: dict) -> list[dict]:
        if outputs["answer"] == generate.INSUFFICIENT:
            return [{"key": "grounded", "score": None, "comment": "refused"}]
        passages = "\n\n".join(c["content"] for c in outputs["citations"])
        resp = await llm.chat.completions.create(
            model=settings.chat_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": JUDGE_PROMPT},
                {"role": "user", "content": f"PASSAGES:\n{passages}\n\nANSWER:\n{outputs['answer']}\n\n"
                                            f"REFERENCE:\n{reference_outputs.get('answer') or ''}"},
            ],
        )
        judge_tokens.append(resp.usage.total_tokens)
        grade = json.loads(resp.choices[0].message.content)
        results = [{"key": "grounded", "score": grade.get("grounded")}]
        return results + ([{"key": "correct", "score": grade["correct"]}] if grade.get("correct") is not None else [])

    return target, judge


async def draft(tenant: str, n: int, out: str) -> None:
    pool, llm, sem = await db.create_pool(), ingest.background_llm(), asyncio.Semaphore(4)
    try:
        rows = await pool.fetch(
            "SELECT source, page, content FROM chunks WHERE tenant = $1 ORDER BY random() LIMIT $2", tenant, n
        )
    finally:
        await pool.close()

    async def write_question(row) -> dict:
        async with sem:
            resp = await llm.chat.completions.create(
                model=settings.ocr_model,
                temperature=0.7,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": DRAFT_PROMPT}, {"role": "user", "content": row["content"]}],
            )
        qa = json.loads(resp.choices[0].message.content)
        return {"question": qa["question"], "source": row["source"], "page": row["page"], "answer": qa["answer"]}

    drafts = await asyncio.gather(*(write_question(r) for r in rows))
    await llm.close()
    with open(out, "w") as f:
        f.writelines(json.dumps(d, ensure_ascii=False) + "\n" for d in drafts)
    print(f"Wrote {len(drafts)} draft questions to {out}. Review them before uploading.")


async def run(tenant: str, dataset: str, concurrency: int, min_score: float | None) -> None:
    pool = await db.create_pool()
    llm = AsyncOpenAI(api_key=settings.openai_api_key, max_retries=5)
    target, judge = bind(pool, llm, tenant)
    try:
        results = await aevaluate(
            target,
            data=dataset,
            evaluators=[retrieval, gate, safety, judge],
            summary_evaluators=[best_threshold],
            experiment_prefix=f"rag-{settings.chat_model}-{settings.embed_dim}d",
            metadata={k: getattr(settings, k) for k in ("chat_model", "embed_model", "embed_dim", "chunk_size",
                                                        "chunk_overlap", "candidates_k", "final_k", "min_similarity",
                                                        "rerank", "aux_model", "ocr_model")},
            max_concurrency=concurrency,
        )
        scores, outputs, refs = defaultdict(list), [], []
        async for row in results:
            outputs.append(row["run"].outputs)
            refs.append(row["example"].outputs or {})
            for r in row["evaluation_results"]["results"]:
                if r.score is not None:
                    scores[r.key].append(r.score)
        print(f"\nExperiment: {results.experiment_name}")
        for key, values in sorted(scores.items()):
            print(f"  {key:22} {sum(values) / len(values):.3f}  (n={len(values)})")
        print(f"  suggested MIN_SIMILARITY = {best_threshold(outputs, refs)['score']} (current {settings.min_similarity})")
        answer_tokens = sum(sum(o["usage"].values()) for o in outputs if o.get("usage"))
        print(f"  OpenAI tokens: {answer_tokens} answering (incl. rerank/rewrite) + {sum(judge_tokens)} judging")
        failing = {k: sum(v) / len(v) for k, v in scores.items() if sum(v) / len(v) < (min_score or 0)}
        if failing:
            raise SystemExit(f"Below --min-score {min_score}: {failing}")
    finally:
        await llm.close()
        await pool.close()


def upload(path: str, dataset: str) -> None:
    client = Client()
    if not client.has_dataset(dataset_name=dataset):
        client.create_dataset(dataset, description="Hybrid RAG questions with expected source/page")
    with open(path) as f:
        rows = [json.loads(line) for line in f if line.strip()]
    client.create_examples(
        dataset_name=dataset,
        examples=[{"inputs": {"question": r.pop("question")}, "outputs": r} for r in rows],
    )
    print(f"Uploaded {len(rows)} examples to '{dataset}'")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    upload_cmd = sub.add_parser("upload")
    upload_cmd.add_argument("path")
    upload_cmd.add_argument("--dataset", default=DATASET)
    draft_cmd = sub.add_parser("draft")
    draft_cmd.add_argument("--tenant", required=True)
    draft_cmd.add_argument("-n", type=int, default=40)
    draft_cmd.add_argument("--out", default="eval.draft.jsonl")
    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("--tenant", required=True)
    run_cmd.add_argument("--concurrency", type=int, default=4)
    run_cmd.add_argument("--min-score", type=float)
    run_cmd.add_argument("--dataset", default=DATASET)
    args = parser.parse_args()
    if args.cmd == "upload":
        upload(args.path, args.dataset)
    elif args.cmd == "draft":
        asyncio.run(draft(args.tenant, args.n, args.out))
    else:
        asyncio.run(run(args.tenant, args.dataset, args.concurrency, args.min_score))
