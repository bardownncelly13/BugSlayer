from collections import defaultdict
from typing import Dict, List

def group_findings_by_file(findings: List[Dict]) -> Dict[str, List[Dict]]:
    grouped = defaultdict(list)
    for finding in findings:
        grouped[finding["path"]].append(finding)
    return grouped
