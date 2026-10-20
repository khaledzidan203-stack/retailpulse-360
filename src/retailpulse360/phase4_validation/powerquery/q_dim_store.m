let
    Source = fnLoadCsv("analytics/dim_store.csv", {
        {"store_key", type text},
        {"store_name", type text},
        {"region_key", type text},
        {"region_name", type text},
        {"city_key", type text},
        {"city_name", type text},
        {"store_profile", type text},
        {"lifecycle_cohort", type text},
        {"open_date", type date},
        {"last_trading_date", type date}
    })
in
    Source
