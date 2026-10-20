let
    Source = fnLoadCsv("analytics/dim_marketplace_account.csv", {
        {"account_key", type text},
        {"account_name", type text},
        {"account_type", type text}
    })
in
    Source
