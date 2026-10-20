let
    Source = fnLoadCsv("staging/source_coverage_official.csv", {
        {"store_key", type text},
        {"date_key", Int64.Type},
        {"channel_key", type text},
        {"coverage_state", type text},
        {"evidence", type text}
    })
in
    Source
