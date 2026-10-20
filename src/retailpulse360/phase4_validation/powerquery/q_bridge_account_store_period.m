let
    Source = fnLoadCsv("analytics/bridge_account_store_period.csv", {
        {"account_key", type text},
        {"store_key", type text},
        {"valid_from", type date},
        {"valid_to", type date}
    })
in
    Source
