# Power BI runtime QA — NOT RUN

This execution has no enabled native Power BI Desktop control. Static files and screenshots do not execute Power Query, DAX or interactive visuals. Final release readiness remains false until the following local checks are recorded.

1. Open the copied PBIP from the generated project. Set pProjectRoot to that local project directory; pGeneration=CURRENT. Refresh and confirm Query1 reports seven PASS checks for G0004.
2. Execute the preserved DAX query from `PowerBI/RetailPulse 360.SemanticModel/DAXQueries/Query 1.dax` in the actual model. Compare with freshly rebuilt CSV/SQLite values. Historical 492 comparisons are not current test evidence.
3. Visit all pages 00–10. Test INDEX navigation, year/month/quarter/store/region filters, reset, cross-highlighting, labels, sorting and negative/blank visual states. Capture filter context and observed versus expected values.
4. Verify Retail/Program locked scopes and effective budget gauge roles, including achievement above 100%. Preserve manual gauge formatting.
5. Check Strict LFL same-store period cohorts and ratio of sums; closed-store historical sales; zero versus missing; Saturday WTD and partial periods; 2025 prior-year unavailable; negative returns.
6. Check Marketplace raw later dates versus common-cutoff matched Retail/digital scopes, and source lag -7 days. Do not add digital attribution to Official.
7. Review the page-08 caption “deficits first” against the current sort behavior and selected filter context; preserve approved sort until the owner reviews any semantic discrepancy. Confirm no truncated labels at the intended display size.
8. Select 00 INDEX and save if desired. This is a manual saved-opening-page step; source saved state was preserved.

Capture template: Date | Desktop version | commit | generated manifest SHA | page/KPI | filters | expected | actual | PASS/FAIL | screenshot/evidence. Fresh screenshots should follow successful refresh. Existing gallery images are prior captures and do not certify current runtime.
