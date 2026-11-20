"""One-time lock atomicity check. Runs ONLY inside the manual verify-lock workflow.

N threads try to create the same ref at once. PASS requires ALL of:
  * exactly one ACQUIRED and N-1 HELD, no errors;
  * the ref points at the commit that was supplied;
  * cleanup (in `finally`, always attempted) deleted the ref;
  * a read-back confirms the ref is gone.
Anything else, including a cleanup failure, is FAIL. Nothing else in the repository is written.
"""
import os
import sys
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor

from .lock import ACQUIRED, HELD, NAMESPACE, LockError, acquire

WORKERS = 10


def run_check(gh, repo, commit_sha, name, workers=WORKERS):
    ref = f"{NAMESPACE}{name}"
    report = {"ref": ref, "results": [], "points_at_commit": False, "cleanup": "not attempted",
              "leftover": None, "error": None}
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(acquire, gh, repo, ref, commit_sha) for _ in range(workers)]
            for f in futures:
                try:
                    report["results"].append(f.result())
                except LockError as err:
                    report["results"].append(f"error: {err}")
                except Exception as err:            # noqa: BLE001 - record, keep collecting, then FAIL
                    report["results"].append(f"error: {type(err).__name__}")
                    report["error"] = report["error"] or type(err).__name__
        try:
            obj = gh.call("GET", f"/repos/{repo}/git/ref/{ref[len('refs/'):]}") or {}
            report["points_at_commit"] = (obj.get("object") or {}).get("sha") == commit_sha
        except Exception as err:                    # noqa: BLE001
            report["error"] = report["error"] or f"read-back: {type(err).__name__}"
    except Exception as err:                        # noqa: BLE001
        report["error"] = report["error"] or type(err).__name__
    finally:
        try:
            gh.call("DELETE", f"/repos/{repo}/git/refs/{ref[len('refs/'):]}")
            report["cleanup"] = "deleted"
        except urllib.error.HTTPError as err:
            report["cleanup"] = "nothing to delete" if err.code in (404, 422) else f"FAILED: HTTP {err.code}"
        except Exception as err:                    # noqa: BLE001
            report["cleanup"] = f"FAILED: {type(err).__name__}"
        try:
            left = gh.call("GET", f"/repos/{repo}/git/matching-refs/{ref[len('refs/'):]}") or []
            report["leftover"] = [x["ref"] for x in left]
        except Exception as err:                    # noqa: BLE001
            report["leftover"] = f"unknown ({type(err).__name__})"
    return report


def passed(report, workers=WORKERS):
    r = report["results"]
    return (report["error"] is None and len(r) == workers and r.count(ACQUIRED) == 1
            and r.count(HELD) == workers - 1 and report["points_at_commit"] is True
            and report["cleanup"] == "deleted" and report["leftover"] == [])


def main(env=os.environ):
    if env.get("GITHUB_ACTIONS") != "true" or env.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        print("refusing to run outside the manual verify-lock workflow")
        return 2
    from .github_api import GitHub
    repo, sha = env["GITHUB_REPOSITORY"], env["GITHUB_SHA"]
    report = run_check(GitHub(env["GITHUB_TOKEN"]), repo, sha, f"verify-{env.get('GITHUB_RUN_ID', '0')}-{int(time.time())}")
    r = report["results"]
    print(f"acquired={r.count(ACQUIRED)} held={r.count(HELD)} other={len(r) - r.count(ACQUIRED) - r.count(HELD)}")
    print(f"points_at_commit={report['points_at_commit']} cleanup={report['cleanup']} "
          f"leftover={report['leftover']} error={report['error']}")
    ok = passed(report)
    print("LOCK ATOMICITY: PASS" if ok else "LOCK ATOMICITY: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
