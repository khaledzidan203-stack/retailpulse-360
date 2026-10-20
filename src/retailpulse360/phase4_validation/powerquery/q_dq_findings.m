let
    Source = fnLoadCsv("analytics/dq_findings.csv", {
        {"check_id", type text},
        {"severity", type text},
        {"source_family", type text},
        {"affected_key", type text},
        {"reason", type text},
        {"evidence", type text}
    })
in
    Source
