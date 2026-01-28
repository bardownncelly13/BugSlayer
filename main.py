from delta import get_changed_files, get_diff_for_file
from scanners.example_scanner import scan_diff
from strategies.triage import TriageStrategy
from strategies.patch import PatchStrategy

def main():
    triage = TriageStrategy()
    patcher = PatchStrategy()

    for file in get_changed_files():
        diff = get_diff_for_file(file)
        findings = scan_diff(diff)

        for finding in findings:
            context = {
                "file": file,
                "diff": diff,
                "finding": finding,
            }

            triage_result = triage.run(context)
            if not triage_result or not triage_result.is_real_issue:
                continue

            context["triage"] = triage_result
            patch = patcher.run(context)

            if patch:
                print("=== Proposed Patch ===")
                print(patch.diff)
                print("======================")

if __name__ == "__main__":
    main()
