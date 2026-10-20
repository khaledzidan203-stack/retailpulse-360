let
    Source = fnLoadCsv("analytics/fact_budget_monthly.csv", {
        {"store_key", type text},
        {"month_start", type date},
        {"channel_key", type text},
        {"monthly_target_cents", Int64.Type},
        {"budget_version", type text}
    })
in
    Source
