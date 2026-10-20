let
    Source = fnLoadCsv("staging/source_coverage_marketplace.csv", {
        {"account_key", type text},
        {"date_key", Int64.Type},
        {"coverage_state", type text},
        {"evidence", type text}
    })
in
    Source
