
class CodeTraceInfo:

    def __init__(self, findings):
        self.vuln_map = self._build_map(findings)

    def _parse_signature(self, sig):
        if not sig or "(" not in sig:
            return sig, ()

        name = sig.split("(")[0]

        params = sig.split("(")[1].rstrip(")")

        if not params.strip():
            return name, ()

        types = []

        for p in params.split(","):
            p = p.strip()

            # remove variable name
            t = p.split(" ")[0]

            types.append(t)

        return name, tuple(types)

    def _build_map(self, findings):

        vuln_map = {}

        for file in findings:
            path = file["path"]

            for vuln in file["vulnerabilities"]:

                func, param_types = self._parse_signature(vuln["function"])

                key = (
                    path,
                    vuln["function_class"],
                    func,
                    param_types
                )

                vuln_map.setdefault(key, []).append(vuln)

        return vuln_map