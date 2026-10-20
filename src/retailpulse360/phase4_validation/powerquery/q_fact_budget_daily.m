let
    Source = fnLoadCsv("analytics/fact_budget_daily.csv", {
        {"store_key", type text},
        {"date_key", Int64.Type},
        {"channel_key", type text},
        {"allocated_budget_cents", Int64.Type},
        {"budget_version", type text},
        {"allocation_policy_version", type text}
    })
in
    Source
